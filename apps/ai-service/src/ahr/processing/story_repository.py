"""Loading candidates and persisting Stories.

Kept apart from `story.py` so the scoring rules stay unit-testable without a
database, which is what AHR-QSO-700 §1 needs for the offline suite.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from ahr.processing.story import (
    CLUSTER_ALGORITHM_VERSION,
    Candidate,
    Cluster,
    PairScore,
    cluster,
    extract_versions,
    independent_sources,
    slugify,
    story_heat,
    tokenize,
)

CANDIDATE_SQL = """
    SELECT ci.id,
           COALESCE(ci.zh_title, ci.title) AS title,
           ci.source_id,
           s.organization,
           s.source_tier,
           ci.content_type,
           COALESCE(ci.published_at, ci.observed_at) AS published_at,
           ci.quality_score,
           COALESCE(
               (SELECT array_agg(DISTINCT ie.entity_id::text)
                  FROM item_entity ie WHERE ie.content_item_id = ci.id),
               ARRAY[]::text[]
           ) AS entity_ids,
           COALESCE(
               (SELECT array_agg(DISTINCT it.topic_id::text)
                  FROM item_topic it WHERE it.content_item_id = ci.id),
               ARRAY[]::text[]
           ) AS topic_ids
      FROM content_item ci
      JOIN source s ON s.id = ci.source_id
     WHERE ci.duplicate_of_id IS NULL
       AND COALESCE(ci.published_at, ci.observed_at) > now() - (%s || ' days')::interval
     ORDER BY published_at DESC
"""


def load_candidates(connection: Any, *, days: int) -> list[Candidate]:
    with connection.cursor() as cursor:
        cursor.execute(CANDIDATE_SQL, (days,))
        rows = cursor.fetchall()

    candidates: list[Candidate] = []
    for row in rows:
        title = row[1] or ""
        candidates.append(
            Candidate(
                item_id=uuid.UUID(str(row[0])),
                title=title,
                source_id=row[2],
                organization=row[3],
                source_tier=row[4] or "",
                content_type=row[5],
                published_at=row[6],
                quality_score=float(row[7]) if row[7] is not None else None,
                entity_ids=frozenset(row[8] or ()),
                topic_ids=frozenset(row[9] or ()),
                tokens=tokenize(title),
                versions=extract_versions(title),
            )
        )
    return candidates


def _locked_item_ids(connection: Any) -> set[uuid.UUID]:
    """Items belonging to a story an editor has locked.

    docs/spec/03 §8: "人工锁定 Story 不自动拆并". They are excluded from
    clustering entirely, so a re-run cannot move them.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT si.content_item_id
              FROM story_item si
              JOIN story s ON s.id = si.story_id
             WHERE s.locked_by_editor
            """
        )
        return {uuid.UUID(str(row[0])) for row in cursor.fetchall()}


def _write_cluster(connection: Any, group: Cluster, now: datetime) -> uuid.UUID:
    primary = group.primary()
    occurred = group.occurred_at()
    members = group.members
    sources = independent_sources(members)
    heat = story_heat(members, occurred, now)

    story_id = uuid.uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO story (
                id, slug, title, occurred_at, first_seen_at, last_updated_at,
                primary_item_id, status, heat_score, independent_source_count,
                item_count, algorithm_version, clustered_at
            ) VALUES (%s, %s, %s, %s, now(), now(), %s, 'PUBLISHED', %s, %s, %s, %s, now())
            RETURNING id
            """,
            (
                story_id,
                slugify(primary.title, occurred),
                primary.title,
                occurred,
                primary.item_id,
                heat,
                sources,
                len(members),
                CLUSTER_ALGORITHM_VERSION,
            ),
        )
        story_id = uuid.UUID(str(cursor.fetchone()[0]))

        for member in members:
            score: PairScore | None = group.scores.get(member.item_id)
            cursor.execute(
                """
                INSERT INTO story_item (
                    story_id, content_item_id, relation_type, independent_source,
                    similarity_score, score_breakdown
                ) VALUES (%s, %s, %s, TRUE, %s, %s::jsonb)
                ON CONFLICT (story_id, content_item_id) DO NOTHING
                """,
                (
                    story_id,
                    member.item_id,
                    "PRIMARY" if member.item_id == primary.item_id else "SUPPORTS",
                    score.total if score else None,
                    json.dumps(score.as_dict() if score else {}),
                ),
            )

        cursor.execute(
            "UPDATE content_item SET story_id = %s WHERE id = ANY(%s)",
            (story_id, [m.item_id for m in members]),
        )
    return story_id


def recluster(connection: Any, *, days: int = 14) -> dict[str, Any]:
    """Rebuild stories for the recent window.

    Unlocked stories in the window are dropped and rebuilt rather than patched:
    incremental merge/split bookkeeping is where clustering implementations
    usually rot, and the window is small enough that a rebuild is cheap.
    """
    now = datetime.now(UTC)
    locked = _locked_item_ids(connection)

    candidates = [c for c in load_candidates(connection, days=days) if c.item_id not in locked]
    groups, suggestions = cluster(candidates)

    with connection.cursor() as cursor:
        # Detach items first so the story rows can go without violating the FK.
        cursor.execute(
            """
            UPDATE content_item SET story_id = NULL
             WHERE story_id IN (SELECT id FROM story WHERE NOT locked_by_editor)
            """
        )
        cursor.execute(
            """
            DELETE FROM story_item
             WHERE story_id IN (SELECT id FROM story WHERE NOT locked_by_editor)
            """
        )
        unlocked = "(SELECT id FROM story WHERE NOT locked_by_editor)"
        cursor.execute(f"DELETE FROM story_topic WHERE story_id IN {unlocked}")
        cursor.execute(f"DELETE FROM story_relation WHERE from_story_id IN {unlocked}")
        cursor.execute("DELETE FROM story WHERE NOT locked_by_editor")

    multi = 0
    for group in groups:
        _write_cluster(connection, group, now)
        if len(group.members) > 1:
            multi += 1

    recorded = _record_suggestions(connection, suggestions)
    connection.commit()

    return {
        "candidates": len(candidates),
        "locked_items": len(locked),
        "stories": len(groups),
        "multi_source_stories": multi,
        "suggestions": recorded,
        "algorithm": CLUSTER_ALGORITHM_VERSION,
    }


def _record_suggestions(
    connection: Any, suggestions: list[tuple[Candidate, Candidate, PairScore]]
) -> int:
    written = 0
    with connection.cursor() as cursor:
        for left, right, score in suggestions:
            # Normalise the pair order so the unique constraint actually
            # deduplicates; without this A/B and B/A are two rows.
            first, second = sorted([left.item_id, right.item_id], key=str)
            cursor.execute(
                """
                INSERT INTO cluster_suggestion (
                    id, left_item_id, right_item_id, score, score_breakdown,
                    reason, algorithm_version
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (left_item_id, right_item_id) DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    first,
                    second,
                    round(score.total, 5),
                    json.dumps(score.as_dict()),
                    "score in review band",
                    CLUSTER_ALGORITHM_VERSION,
                ),
            )
            written += cursor.rowcount
    return written


def sync_item_heat(connection: Any) -> int:
    """Push story heat and source counts down onto their items.

    The feed and hot list read content_item, so without this the site would keep
    showing the pre-M3 approximation while the stories held the real numbers.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE content_item ci
               SET independent_source_count = s.independent_source_count,
                   hot_score = s.heat_score,
                   hot_scored_at = now()
              FROM story s
             WHERE ci.story_id = s.id
            """
        )
        updated = int(cursor.rowcount)
    connection.commit()
    return updated

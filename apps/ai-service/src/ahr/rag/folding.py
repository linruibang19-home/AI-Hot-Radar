"""Story folding (M4 B6, AHR-RAG-400 §7).

The very first smoke test found the Anthropic incident occupying three evidence
slots — Ars Technica, The Verge and 量子位 each reporting the same disclosure.
Three outlets is corroboration, not three facts, and spending three of ten slots
on it costs the answer everything those slots could have covered.

§7 fixes the shape: **one primary-source passage per story, plus at most two
from other independent sources**. Independence is per *source*, not per article:
two pieces from the same outlet about one event are one source twice.

M3's clustering is what makes this possible without any new machinery. The
external design this project was compared against needs GraphRAG entity groups
to reach the same place; `story_item` already holds it, built by containment
clustering and costing no model call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# §7: one main source plus two corroborating ones.
MAX_PER_STORY = 3
MAX_SUPPORTING_SOURCES = 2

# Ordering for "which source speaks for this event". A first-hand announcement
# outranks coverage of it.
_TIER_RANK = {"primary": 0, "expert": 1, "authoritative_secondary": 2, "secondary": 3}


@dataclass(frozen=True)
class ChunkFacts:
    """What folding needs to know about a retrieved chunk."""

    chunk_id: str
    content_item_id: str
    story_id: str | None
    source_id: str
    source_tier: str


def load_chunk_facts(connection: Any, chunk_ids: list[str]) -> dict[str, ChunkFacts]:
    if not chunk_ids:
        return {}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ch.id::text, ci.id::text, ci.story_id::text, s.id, s.source_tier
              FROM content_chunk ch
              JOIN content_revision cr ON cr.id = ch.content_revision_id
              JOIN content_item ci ON ci.id = cr.content_item_id
              JOIN source s ON s.id = ci.source_id
             WHERE ch.id = ANY(%s::uuid[])
            """,
            (chunk_ids,),
        )
        return {
            row[0]: ChunkFacts(
                chunk_id=row[0],
                content_item_id=row[1],
                story_id=row[2],
                source_id=row[3],
                source_tier=row[4] or "secondary",
            )
            for row in cursor.fetchall()
        }


def fold_by_story(
    ranked_chunk_ids: list[str],
    facts: dict[str, ChunkFacts],
    *,
    limit: int,
) -> list[str]:
    """Collapse same-event passages, preserving retrieval order otherwise.

    Chunks with no story are left alone: most releases are genuinely covered by
    one outlet, and folding is only meaningful where an event was reported more
    than once.

    Rank order is respected inside a story rather than re-sorted by tier. The
    reranker already judged relevance to *this* question, and a first-hand
    release note that answers it less directly should not displace the article
    that answers it. Tier decides who counts as the main source when they are
    otherwise equal, which is what `_TIER_RANK` is for.
    """
    kept: list[str] = []
    per_story: dict[str, int] = {}
    sources_per_story: dict[str, set[str]] = {}
    seen_items: set[str] = set()

    for chunk_id in ranked_chunk_ids:
        fact = facts.get(chunk_id)
        if fact is None:
            continue

        story = fact.story_id
        if story is None:
            kept.append(chunk_id)
        else:
            taken = per_story.get(story, 0)
            if taken >= MAX_PER_STORY:
                continue

            sources = sources_per_story.setdefault(story, set())
            if fact.source_id in sources:
                # Same outlet, same event: one source counted twice adds no
                # independent confirmation.
                continue
            if len(sources) > MAX_SUPPORTING_SOURCES:
                continue

            sources.add(fact.source_id)
            per_story[story] = taken + 1
            kept.append(chunk_id)

        seen_items.add(fact.content_item_id)
        if len(kept) >= limit:
            break

    return kept


def main_source_first(chunk_ids: list[str], facts: dict[str, ChunkFacts]) -> list[str]:
    """Within each story, put the highest-tier passage first.

    §8 requires fact-check answers to lead with a first-hand source where one
    exists. This only reorders inside a story, so the overall relevance ordering
    between different events is untouched.
    """
    by_story: dict[str | None, list[str]] = {}
    order: list[str | None] = []
    for chunk_id in chunk_ids:
        fact = facts.get(chunk_id)
        story = fact.story_id if fact else None
        if story not in by_story:
            by_story[story] = []
            order.append(story)
        by_story[story].append(chunk_id)

    result: list[str] = []
    for story in order:
        group = by_story[story]
        if story is None or len(group) == 1:
            result.extend(group)
            continue
        result.extend(
            sorted(
                group,
                key=lambda cid: _TIER_RANK.get(
                    facts[cid].source_tier if cid in facts else "secondary", 9
                ),
            )
        )
    return result

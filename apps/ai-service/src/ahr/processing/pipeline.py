"""Content processing pipeline (M2).

Takes persisted content and prepares it for the website and for RAG:

    chunk -> near-duplicate check -> LLM structuring -> quality score

Enrichment failure never blocks the rest: a document that the model cannot
structure keeps its extracted body and stays browsable, which is exactly what
AHR-ROADMAP-800's M2 acceptance ("content still browsable when the model is
unavailable") requires.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from ahr.config import get_settings
from ahr.processing.chunking import chunk_document
from ahr.processing.dedup import is_near_duplicate, simhash, to_signed_64
from ahr.processing.llm import (
    EnrichmentSchemaError,
    LlmClient,
    LlmUnavailableError,
    TokenUsage,
    build_client_from_env,
    prompt_version,
)
from ahr.processing.schemas import EnrichmentResult
from ahr.processing.topics import (
    known_slugs,
    link_topics,
    load_display,
    load_taxonomy,
    seed_topics,
)

logger = logging.getLogger(__name__)

SOURCE_AUTHORITY = {"primary": 90, "secondary": 65, "expert": 75, "community": 40}

# Below this the body is a stub — a bare version bump, a one-line note — and a
# summary of it carries no information the title does not already give. Spending
# a model call on those is pure cost, so they are marked SKIPPED and stay
# browsable with their original title and excerpt.
MIN_BODY_CHARS_FOR_ENRICHMENT = 200


@dataclass
class ProcessStats:
    chunked: int = 0
    chunks_written: int = 0
    closed_empty: int = 0
    near_duplicates: int = 0
    enriched: int = 0
    enrich_failed: int = 0
    skipped_thin: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    llm_unavailable: bool = False


def chunk_revision(connection: Any, revision_id: uuid.UUID, body: str) -> int:
    """Replace a revision's chunks. Returns the number written."""
    chunks = chunk_document(body)
    if not chunks:
        return 0

    with connection.cursor() as cursor:
        # Rebuild rather than merge: a revision's chunk set must match its body.
        cursor.execute("DELETE FROM content_chunk WHERE content_revision_id = %s", (revision_id,))
        for chunk in chunks:
            cursor.execute(
                """
                INSERT INTO content_chunk (
                    id, content_revision_id, ordinal, heading_path, body_text,
                    token_count, char_start, char_end
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (content_revision_id, ordinal) DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    revision_id,
                    chunk.ordinal,
                    chunk.heading_path,
                    chunk.text,
                    chunk.token_count,
                    chunk.char_start,
                    chunk.char_end,
                ),
            )
    return len(chunks)


def find_near_duplicate(connection: Any, item_id: uuid.UUID, fingerprint: int) -> uuid.UUID | None:
    """Return an earlier item that this one near-duplicates, if any.

    Only earlier items are considered so the original keeps its identity and the
    copy is the one marked.
    """
    if not fingerprint:
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.id, cr.simhash
              FROM content_item ci
              JOIN content_revision cr ON cr.id = ci.current_revision_id
             WHERE cr.simhash IS NOT NULL
               AND ci.id <> %s
               AND ci.duplicate_of_id IS NULL
               AND ci.observed_at > now() - interval '14 days'
             ORDER BY ci.observed_at DESC
             LIMIT 500
            """,
            (item_id,),
        )
        rows = cursor.fetchall()

    from ahr.processing.dedup import from_signed_64

    for other_id, other_hash in rows:
        if is_near_duplicate(fingerprint, from_signed_64(int(other_hash))):
            return uuid.UUID(str(other_id))
    return None


def _store_enrichment(
    connection: Any,
    item_id: uuid.UUID,
    result: EnrichmentResult,
    *,
    source_tier: str,
    model_name: str,
    vocabulary: set[str],
) -> None:
    score = result.quality_score(source_authority=SOURCE_AUTHORITY.get(source_tier, 50))

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE content_item
               SET summary_zh = %s, zh_title = %s, content_type = %s,
                   quality_score = %s, enrichment_state = 'ENRICHED',
                   enrichment_error = NULL, prompt_version = %s, model_name = %s,
                   enriched_at = now(), workflow_state = 'ENRICHED',
                   attributes = attributes || %s::jsonb, updated_at = now()
             WHERE id = %s
            """,
            (
                result.summary_zh,
                result.zh_title,
                result.content_type,
                score,
                prompt_version(),
                model_name,
                json.dumps({"quality_factors": result.quality_factors.model_dump()}),
                item_id,
            ),
        )

        for entity in result.entities:
            slug = entity.name.strip().lower().replace(" ", "-")[:160]
            if not slug:
                continue
            cursor.execute(
                """
                INSERT INTO entity (id, slug, name, entity_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (uuid.uuid4(), slug, entity.name.strip()[:200], entity.type),
            )
            entity_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO item_entity (content_item_id, entity_id, role, confidence)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (content_item_id, entity_id) DO UPDATE
                    SET role = EXCLUDED.role, confidence = EXCLUDED.confidence
                """,
                (item_id, entity_id, entity.role, entity.confidence),
            )

    # Topics are normalised against config/taxonomy.yaml; a label that does not
    # resolve is dropped rather than creating a one-off topic page.
    link_topics(
        connection,
        item_id,
        [(topic.slug, topic.confidence) for topic in result.topics],
        vocabulary,
    )


def _record_usage(
    connection: Any,
    item_id: uuid.UUID | None,
    usage: TokenUsage,
    *,
    model: str,
    succeeded: bool,
) -> None:
    """Persist provider-reported usage so spend is auditable (AHR-QSO-700 §5)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO llm_usage (
                id, content_item_id, operation, model, prompt_version,
                prompt_tokens, completion_tokens, cached_tokens,
                attempts, succeeded, latency_ms
            ) VALUES (%s, %s, 'enrich', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid.uuid4(),
                item_id,
                model,
                prompt_version(),
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cached_tokens,
                usage.attempts,
                succeeded,
                usage.latency_ms,
            ),
        )


def _mark_enrichment_failed(connection: Any, item_id: uuid.UUID, *, state: str, error: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE content_item
               SET enrichment_state = %s, enrichment_error = %s, updated_at = now()
             WHERE id = %s
            """,
            (state, error[:500], item_id),
        )


def _unchunked_revisions(connection: Any, limit: int) -> list[tuple[Any, ...]]:
    """Current revisions that have a body but no chunks.

    Selected by the invariant this maintains — every current revision is split —
    and deliberately *not* by `enrichment_state`. Chunking is a pure function of
    the body; giving it the LLM's lifecycle meant a document could only ever be
    split during the one pass that also enriched it. A re-crawl then moved
    `current_revision_id` forward while the item stayed ENRICHED, so nothing
    ever split the new body and the chunks stayed attached to a revision no
    query joins to.

    Ingestion now reopens superseded items, which stops new cases arising; this
    query is what repairs the ones already in that state, and what keeps a
    failed or skipped enrichment from costing the item its retrievability.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.current_revision_id, cr.body_text
              FROM content_item ci
              JOIN content_revision cr ON cr.id = ci.current_revision_id
             WHERE ci.duplicate_of_id IS NULL
               AND length(cr.body_text) > 0
               AND NOT EXISTS (
                   SELECT 1 FROM content_chunk cc
                    WHERE cc.content_revision_id = ci.current_revision_id
               )
             ORDER BY ci.published_at DESC NULLS LAST
             LIMIT %s
            """,
            (limit,),
        )
        return list(cursor.fetchall())


def chunk_current_revisions(connection: Any, limit: int) -> tuple[int, int]:
    """Split every current revision that is missing its chunks.

    Returns (revisions chunked, chunks written).
    """
    revisions = 0
    written = 0
    for revision_id, body in _unchunked_revisions(connection, limit):
        count = chunk_revision(connection, uuid.UUID(str(revision_id)), body)
        if count:
            revisions += 1
            written += count
    connection.commit()
    return revisions, written


def close_empty_bodies(connection: Any) -> int:
    """Mark items whose current revision has no body at all.

    These are release tags with no notes and listing pages that yielded no
    article. The processing query requires a non-empty body, so they matched
    nothing and sat in PENDING permanently — a backlog figure that could never
    reach zero, which is a backlog figure nobody can act on.

    Safe to close now that ingestion reopens an item when a new body arrives:
    if one of these ever gains real content, the next revision returns it to
    PENDING rather than leaving it retired on the strength of an old emptiness.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE content_item ci
               SET enrichment_state = 'SKIPPED',
                   enrichment_error = 'no body text extracted',
                   updated_at = now()
              FROM content_revision cr
             WHERE cr.id = ci.current_revision_id
               AND ci.enrichment_state = 'PENDING'
               AND length(cr.body_text) = 0
            """
        )
        closed = int(cursor.rowcount)
    connection.commit()
    return closed


def _pending_items(connection: Any, limit: int) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.id, ci.title, ci.source_id, ci.source_tier,
                   cr.id, cr.body_text, s.name
              FROM content_item ci
              JOIN content_revision cr ON cr.id = ci.current_revision_id
              JOIN source s ON s.id = ci.source_id
             WHERE ci.enrichment_state IN ('PENDING', 'FAILED')
               AND ci.duplicate_of_id IS NULL
               AND length(cr.body_text) > 0
             ORDER BY ci.published_at DESC NULLS LAST
             LIMIT %s
            """,
            (limit,),
        )
        return list(cursor.fetchall())


async def process_pending(
    *, limit: int, enrich: bool = True, client: LlmClient | None = None
) -> ProcessStats:
    """Chunk, de-duplicate and enrich pending content."""
    stats = ProcessStats()

    llm: LlmClient | None = client
    owns_client = False
    model_name = ""
    if enrich and llm is None:
        try:
            llm = build_client_from_env()
            owns_client = True
        except LlmUnavailableError as exc:
            # Chunking and dedup are still worth doing without a model.
            logger.warning("llm not configured, skipping enrichment: %s", exc)
            stats.llm_unavailable = True
            llm = None

    if llm is not None:
        model_name = llm._config.model  # noqa: SLF001 - recorded for provenance
        if owns_client:
            await llm.__aenter__()

    try:
        with psycopg.connect(get_settings().database_url) as connection:
            # The controlled vocabulary is small and rarely changes, so seeding
            # it per run keeps topic pages consistent without a separate step.
            taxonomy = load_taxonomy()
            seed_topics(connection, taxonomy, load_display())
            vocabulary = known_slugs(taxonomy)
            connection.commit()

            # Chunking runs as its own stage over everything that is missing
            # chunks, not only over what is queued for the model. It is cheap
            # and deterministic, and an item whose enrichment failed or was
            # skipped as thin should still be retrievable.
            chunked, chunks_written = chunk_current_revisions(connection, limit)
            stats.chunked += chunked
            stats.chunks_written += chunks_written
            stats.closed_empty += close_empty_bodies(connection)

            for row in _pending_items(connection, limit):
                item_id, title, _source_id, source_tier, revision_id, body, source_name = row
                item_id = uuid.UUID(str(item_id))
                revision_id = uuid.UUID(str(revision_id))

                fingerprint = simhash(body)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE content_revision SET simhash = %s WHERE id = %s",
                        (to_signed_64(fingerprint), revision_id),
                    )

                original = find_near_duplicate(connection, item_id, fingerprint)
                if original is not None:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE content_item
                               SET duplicate_of_id = %s, duplicate_kind = 'NEAR',
                                   enrichment_state = 'SKIPPED', updated_at = now()
                             WHERE id = %s
                            """,
                            (original, item_id),
                        )
                    stats.near_duplicates += 1
                    connection.commit()
                    continue

                if len(body.strip()) < MIN_BODY_CHARS_FOR_ENRICHMENT:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE content_item SET enrichment_state = 'SKIPPED',"
                            " enrichment_error = 'body below enrichment threshold'"
                            " WHERE id = %s",
                            (item_id,),
                        )
                    stats.skipped_thin += 1
                    connection.commit()
                    continue

                if llm is None:
                    connection.commit()
                    continue

                try:
                    result, usage = await llm.enrich(
                        title=title or "", body_text=body, source_name=source_name
                    )
                    _record_usage(connection, item_id, usage, model=model_name, succeeded=True)
                    stats.prompt_tokens += usage.prompt_tokens
                    stats.completion_tokens += usage.completion_tokens
                    stats.cached_tokens += usage.cached_tokens
                    _store_enrichment(
                        connection,
                        item_id,
                        result,
                        source_tier=source_tier,
                        model_name=model_name,
                        vocabulary=vocabulary,
                    )
                    stats.enriched += 1
                except EnrichmentSchemaError as exc:
                    # One repair already happened inside enrich(); do not loop.
                    _mark_enrichment_failed(
                        connection, item_id, state="DEAD_LETTER", error=str(exc)
                    )
                    stats.enrich_failed += 1
                except LlmUnavailableError as exc:
                    _mark_enrichment_failed(connection, item_id, state="FAILED", error=str(exc))
                    stats.enrich_failed += 1
                    stats.llm_unavailable = True
                    connection.commit()
                    logger.warning("llm unavailable, stopping enrichment early: %s", exc)
                    break

                connection.commit()
                await asyncio.sleep(0.2)
    finally:
        if llm is not None and owns_client:
            await llm.__aexit__()

    return stats

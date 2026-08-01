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
    build_client_from_env,
    prompt_version,
)
from ahr.processing.schemas import EnrichmentResult

logger = logging.getLogger(__name__)

SOURCE_AUTHORITY = {"primary": 90, "secondary": 65, "expert": 75, "community": 40}


@dataclass
class ProcessStats:
    chunked: int = 0
    chunks_written: int = 0
    near_duplicates: int = 0
    enriched: int = 0
    enrich_failed: int = 0
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
            for row in _pending_items(connection, limit):
                item_id, title, _source_id, source_tier, revision_id, body, source_name = row
                item_id = uuid.UUID(str(item_id))
                revision_id = uuid.UUID(str(revision_id))

                written = chunk_revision(connection, revision_id, body)
                if written:
                    stats.chunked += 1
                    stats.chunks_written += written

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

                if llm is None:
                    connection.commit()
                    continue

                try:
                    result = await llm.enrich(
                        title=title or "", body_text=body, source_name=source_name
                    )
                    _store_enrichment(
                        connection,
                        item_id,
                        result,
                        source_tier=source_tier,
                        model_name=model_name,
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

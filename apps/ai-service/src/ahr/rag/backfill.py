"""Populate content_chunk.embedding (M4).

Runs over chunks that have no vector yet. Idempotent by construction: the
selection is `embedding IS NULL`, so an interrupted run resumes exactly where it
stopped and a completed run is a no-op.
"""

from __future__ import annotations

import logging
from typing import Any

from ahr.rag.context import build_embedding_text
from ahr.rag.embeddings import DEFAULT_BATCH_SIZE, EmbeddingClient, EmbeddingUnavailableError

logger = logging.getLogger(__name__)


def _pending(connection: Any, limit: int, model: str) -> list[tuple[Any, str]]:
    """Chunks still needing a vector, paired with their embedding input.

    Also picks up chunks embedded by a *different* model: mixing models in one
    column makes distances meaningless, so switching models must re-embed rather
    than leave a silently incomparable mixture behind.

    The join exists to build the context header — a bare changelog bullet is
    nearly unsearchable without knowing which product and release it belongs to.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ch.id, ch.body_text, ch.heading_path,
                   COALESCE(ci.zh_title, ci.title), s.name,
                   COALESCE(ci.published_at, ci.observed_at)
              FROM content_chunk ch
              JOIN content_revision cr ON cr.id = ch.content_revision_id
              JOIN content_item ci ON ci.id = cr.content_item_id
             JOIN source s ON s.id = ci.source_id
             WHERE ch.is_active
               AND (ch.embedding IS NULL
                OR ch.embedding_model IS DISTINCT FROM %s)
             ORDER BY ch.created_at
             LIMIT %s
            """,
            (model, limit),
        )
        return [
            (
                row[0],
                build_embedding_text(
                    body_text=row[1],
                    heading_path=list(row[2] or []),
                    title=row[3],
                    source_name=row[4],
                    published_at=row[5],
                ),
            )
            for row in cursor.fetchall()
        ]


async def backfill_embeddings(
    connection: Any,
    *,
    client: EmbeddingClient,
    limit: int = 500,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    rows = _pending(connection, limit, client.model_name)
    written = 0
    failed_batches = 0

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        try:
            vectors = await client.embed([text for _, text in batch])
        except EmbeddingUnavailableError as exc:
            # Stop rather than burn the remaining budget against a provider that
            # is down; the next run resumes from the same place.
            failed_batches += 1
            logger.warning("embedding batch failed, stopping: %s", exc)
            break

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                UPDATE content_chunk
                   SET embedding = %s::vector, embedding_model = %s
                 WHERE id = %s
                """,
                [
                    (str(vector), client.model_name, chunk_id)
                    for (chunk_id, _), vector in zip(batch, vectors, strict=True)
                ],
            )
        connection.commit()
        written += len(batch)

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM content_chunk WHERE is_active AND embedding IS NULL")
        remaining = cursor.fetchone()[0]

    return {
        "candidates": len(rows),
        "embedded": written,
        "failed_batches": failed_batches,
        "remaining": remaining,
        "model": client.model_name,
        "calls": client.usage.calls,
        "prompt_tokens": client.usage.prompt_tokens,
    }

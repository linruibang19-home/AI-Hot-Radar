"""Ingestion persistence.

Writes the fact layers defined in AHR-SPEC-000 §7:

    raw_document      - the original response, internal audit only
    content_item      - one normalised piece of content
    content_revision  - the versioned title/body for that item
    fulltext_attempt  - the gate verdict, so source health is auditable

Idempotency follows AHR-INGEST-1000 §11: `source_id + external_id` first, then
`canonical_url_hash`, then `content_sha256`. Re-running a batch therefore has
exactly-once *effect* without assuming exactly-once delivery.

The cursor advances only after the batch and its outbox rows commit, so a crash
mid-batch replays rather than skipping content.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ahr.ingestion.fulltext_gate import Decision, GateResult
from ahr.ingestion.health import next_state_after_failure
from ahr.ingestion.models import DiscoveredDocument, SourceConfig, SourceCursor
from ahr.ingestion.titles import resolve_title
from ahr.ingestion.urls import canonicalize_url, content_hash, url_hash

EXTRACTION_VERSION = "trafilatura-2.2.0/ahr-1"

# Clock skew between us and a publisher is minutes, not days. OpenAlex returns
# expected-publication dates decades out (2045 was observed), and a future
# published_at pins an item to the top of every time-ordered view forever.
# AHR-INGEST-1000 §5 forbids fabricating a publication date, so an implausible
# one is discarded rather than clamped to now: observed_at still records when we
# actually saw it.
PUBLISHED_AT_FUTURE_GRACE = timedelta(hours=6)


def sanitize_published_at(
    value: datetime | None, *, now: datetime | None = None
) -> datetime | None:
    """Drop publication dates that cannot be real."""
    if value is None:
        return None
    reference = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if value > reference + PUBLISHED_AT_FUTURE_GRACE:
        return None
    # A date before the web existed is equally a parsing artefact.
    if value.year < 1990:
        return None
    return value


@dataclass
class PersistStats:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    fulltext_accepted: int = 0
    metadata_only: int = 0
    rejected: int = 0


def start_crawl_run(connection: Any, source_id: str, *, trigger: str = "manual") -> uuid.UUID:
    run_id = uuid.uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO crawl_run (id, source_id, trigger_type, status, trace_id, started_at)
            VALUES (%s, %s, %s, 'RUNNING', %s, now())
            """,
            (run_id, source_id, trigger, uuid.uuid4().hex[:32]),
        )
    return run_id


def finish_crawl_run(
    connection: Any,
    run_id: uuid.UUID,
    *,
    status: str,
    stats: PersistStats,
    discovered: int,
    http_status: int | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE crawl_run
               SET status = %s, discovered_count = %s, fetched_count = %s,
                   accepted_count = %s, rejected_count = %s, http_status = %s,
                   error_code = %s, error_detail = %s, finished_at = now()
             WHERE id = %s
            """,
            (
                status,
                discovered,
                stats.inserted + stats.updated,
                stats.fulltext_accepted,
                stats.rejected,
                http_status,
                error_code,
                (error_detail or "")[:500] or None,
                run_id,
            ),
        )


def persist_document(
    connection: Any,
    *,
    source: SourceConfig,
    item: DiscoveredDocument,
    body_text: str,
    body_markdown: str | None,
    gate: GateResult,
    run_id: uuid.UUID | None = None,
    raw_body: bytes | None = None,
    requested_url: str | None = None,
    raw_content_type: str | None = None,
    http_status: int | None = None,
    response_headers: dict[str, str] | None = None,
    final_url: str | None = None,
    extractor: str = "api_body",
    stats: PersistStats | None = None,
) -> uuid.UUID | None:
    """Persist one discovered document and its extraction.

    Returns the `content_item` id, or None when the item was already present
    with identical content.
    """
    stats = stats or PersistStats()
    canonical = canonicalize_url(item.candidate_url)
    canonical_hash = url_hash(canonical)
    content_type = (
        raw_content_type or ("text/html" if item.requires_fetch else "application/json")
    ).split(";", 1)[0][:200]
    now = datetime.now(UTC)

    with connection.cursor() as cursor:
        # --- raw_document: internal audit copy of what we actually received ---
        raw_id = uuid.uuid4()
        cursor.execute(
            """
            INSERT INTO raw_document (
                id, source_id, crawl_run_id, external_id, requested_url, final_url,
                canonical_url, canonical_url_hash, http_status, response_headers,
                content_type, body_bytes, body_sha256, fetched_at,
                parser_version, processing_status, discovery_summary
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_id, external_id) DO UPDATE SET
                crawl_run_id = EXCLUDED.crawl_run_id,
                requested_url = EXCLUDED.requested_url,
                final_url = EXCLUDED.final_url,
                canonical_url = EXCLUDED.canonical_url,
                canonical_url_hash = EXCLUDED.canonical_url_hash,
                http_status = EXCLUDED.http_status,
                response_headers = EXCLUDED.response_headers,
                content_type = EXCLUDED.content_type,
                body_bytes = EXCLUDED.body_bytes,
                body_sha256 = EXCLUDED.body_sha256,
                fetched_at = EXCLUDED.fetched_at,
                parser_version = EXCLUDED.parser_version,
                discovery_summary = EXCLUDED.discovery_summary,
                processing_status = EXCLUDED.processing_status
            RETURNING id
            """,
            (
                raw_id,
                source.id,
                run_id,
                item.external_id,
                requested_url or item.candidate_url,
                final_url or item.candidate_url,
                canonical,
                canonical_hash,
                http_status,
                json.dumps(response_headers or {}),
                content_type,
                raw_body,
                hashlib.sha256(raw_body).hexdigest() if raw_body else None,
                now,
                EXTRACTION_VERSION,
                "PARSED" if gate.accepted else "FETCHED",
                item.discovery_summary,
            ),
        )
        row = cursor.fetchone()
        raw_id = row[0] if row else raw_id

        # A rejected body must not become a content_item: the item would look
        # like real content to every downstream consumer including RAG.
        if gate.decision is Decision.REJECTED:
            _record_attempt(cursor, source, raw_id, canonical, gate, extractor)
            stats.rejected += 1
            return None

        # A listing page that misses its heading selector falls back to the
        # anchor's text or href, which is how five sources ended up with URLs,
        # "Read More" and author/date decoration as titles. Resolved once here so
        # content_item and content_revision cannot disagree, and so a new adapter
        # inherits the protection without remembering to ask for it.
        resolved_title = (
            resolve_title(item.title_hint, body_text=body_text, fallback=canonical) or canonical
        )

        # --- content_item: the normalised unit -------------------------------
        item_id = uuid.uuid4()
        cursor.execute(
            """
            INSERT INTO content_item (
                id, source_id, external_id, canonical_url, canonical_url_hash,
                item_type, language, title, published_at, observed_at,
                workflow_state, public_render, source_tier, attributes
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
            )
            ON CONFLICT (source_id, external_id) DO UPDATE SET
                title = EXCLUDED.title,
                published_at = COALESCE(EXCLUDED.published_at, content_item.published_at),
                workflow_state = EXCLUDED.workflow_state,
                version = content_item.version + 1,
                updated_at = now()
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                item_id,
                source.id,
                item.external_id,
                canonical,
                canonical_hash,
                _item_type(source),
                None,
                resolved_title[:500],
                sanitize_published_at(item.published_at_hint, now=now),
                now,
                "PARSED" if gate.accepted else "DISCOVERED",
                "excerpt_link",
                source.tier,
                json.dumps(item.attributes or {}),
            ),
        )
        result = cursor.fetchone()
        if result is None:
            stats.skipped += 1
            return None
        item_id, was_inserted = uuid.UUID(str(result[0])), bool(result[1])
        if was_inserted:
            stats.inserted += 1
        else:
            stats.updated += 1

        # --- content_revision: the versioned body ----------------------------
        body_sha = content_hash(body_text)
        cursor.execute(
            "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM content_revision"
            " WHERE content_item_id = %s",
            (item_id,),
        )
        next_revision = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO content_revision (
                id, content_item_id, raw_document_id, revision_no, title,
                body_markdown, body_text, excerpt, discovery_summary,
                content_sha256, extraction_method, extraction_version,
                quality_score, quality_decision, quality_reasons
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
            )
            ON CONFLICT (content_item_id, content_sha256) DO NOTHING
            RETURNING id
            """,
            (
                uuid.uuid4(),
                item_id,
                raw_id,
                next_revision,
                resolved_title[:500],
                body_markdown,
                body_text,
                body_text[:500] if body_text else None,
                item.discovery_summary,
                body_sha,
                extractor,
                EXTRACTION_VERSION,
                _quality_score(gate),
                gate.decision.value,
                json.dumps([gate.reason_code] if gate.reason_code else []),
            ),
        )
        revision = cursor.fetchone()
        if revision:
            # A row only lands here when the body hash changed, so every derived
            # artefact — chunks, embeddings, zh_title, summary, entities — now
            # describes text nobody reads any more. Moving the pointer without
            # reopening the item left it ENRICHED against a superseded body, and
            # since the processing query polls `enrichment_state`, the new body
            # was never split: 1.4% of the corpus went missing from retrieval
            # while still looking healthy in every count.
            #
            # Known duplicates keep their state: they are excluded from
            # processing by `duplicate_of_id`, so reopening them would park them
            # in PENDING permanently.
            cursor.execute(
                """
                UPDATE content_item
                   SET current_revision_id = %s,
                       enrichment_state = CASE
                           WHEN duplicate_of_id IS NULL THEN 'PENDING'
                           ELSE enrichment_state
                       END,
                       updated_at = now()
                 WHERE id = %s
                """,
                (revision[0], item_id),
            )
            # AHR-ARCH-200 §6: the outbox row commits with the business write.
            #
            # Stated precisely, because the obvious reading is wrong: this row
            # is *written* transactionally and is *not read by anything*. What
            # actually stops enrichment missing a document is the UPDATE above,
            # which reopens the item as PENDING for the poller. Keeping the
            # write means a consumer can be added without redoing it; until
            # then `retention.prune_outbox` stops the table growing forever.
            cursor.execute(
                """
                INSERT INTO outbox_event (
                    id, aggregate_type, aggregate_id, event_type, payload, trace_id
                )
                VALUES (%s, 'content_item', %s, 'content.parsed', %s::jsonb, %s)
                """,
                (
                    uuid.uuid4(),
                    item_id,
                    json.dumps({"content_item_id": str(item_id), "source_id": source.id}),
                    uuid.uuid4().hex[:32],
                ),
            )

        _record_attempt(cursor, source, raw_id, canonical, gate, extractor)

    if gate.decision is Decision.ACCEPTED:
        stats.fulltext_accepted += 1
    elif gate.decision is Decision.METADATA_ONLY:
        stats.metadata_only += 1

    return item_id


def _record_attempt(
    cursor: Any,
    source: SourceConfig,
    raw_id: uuid.UUID,
    canonical: str,
    gate: GateResult,
    extractor: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO fulltext_attempt (
            id, source_id, raw_document_id, canonical_url, decision,
            reason_code, body_chars, paragraph_count, link_density, extractor
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid.uuid4(),
            source.id,
            raw_id,
            canonical,
            gate.decision.value,
            gate.reason_code,
            gate.body_chars,
            gate.paragraph_count,
            round(gate.link_density, 5),
            extractor,
        ),
    )


def _item_type(source: SourceConfig) -> str:
    if source.profile in ("github_release_api", "github_repo_activity"):
        return "release_note"
    if source.profile == "docs_changelog":
        return "changelog"
    if source.profile == "arxiv_feed_paper":
        return "paper"
    return "article"


def _quality_score(gate: GateResult) -> float:
    """Provisional 0-1 score from gate signals.

    The full weighted formula (AHR-PRD-100 §4) needs LLM signals that arrive in
    M2; this keeps the column populated and ordered sensibly until then.
    """
    if gate.decision is not Decision.ACCEPTED:
        return 0.0
    length_score = min(gate.body_chars / 4000.0, 1.0)
    density_penalty = max(0.0, gate.link_density - 0.1)
    return round(max(0.0, min(0.5 + 0.5 * length_score - density_penalty, 0.9999)), 4)


def save_cursor(connection: Any, source_id: str, cursor_state: SourceCursor) -> None:
    """Advance the source cursor. Call only after the batch has been written."""
    payload = {
        "newest_entry_time": cursor_state.newest_entry_time.isoformat()
        if cursor_state.newest_entry_time
        else None,
        "max_external_id": cursor_state.max_external_id,
        **(cursor_state.extra or {}),
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO source_cursor (
                source_id, cursor_json, etag, last_modified, version, updated_at
            )
            VALUES (%s, %s::jsonb, %s, %s, 1, now())
            ON CONFLICT (source_id) DO UPDATE SET
                cursor_json = EXCLUDED.cursor_json,
                etag = EXCLUDED.etag,
                last_modified = EXCLUDED.last_modified,
                version = source_cursor.version + 1,
                updated_at = now()
            """,
            (source_id, json.dumps(payload), cursor_state.etag, cursor_state.last_modified),
        )


def load_cursor(connection: Any, source_id: str) -> SourceCursor:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT cursor_json, etag, last_modified FROM source_cursor WHERE source_id = %s",
            (source_id,),
        )
        row = cursor.fetchone()

    if not row:
        return SourceCursor()

    payload, etag, last_modified = row
    newest = payload.get("newest_entry_time") if isinstance(payload, dict) else None
    return SourceCursor(
        etag=etag,
        last_modified=last_modified,
        newest_entry_time=datetime.fromisoformat(newest) if newest else None,
        max_external_id=(payload or {}).get("max_external_id"),
        extra={
            k: v
            for k, v in (payload or {}).items()
            if k not in ("newest_entry_time", "max_external_id")
        },
    )


def update_source_state(
    connection: Any,
    source_id: str,
    *,
    state: str,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    with connection.cursor() as cursor:
        if error_code:
            cursor.execute(
                """
                UPDATE source SET runtime_state = %s, last_error_code = %s,
                       last_error_detail = %s, consecutive_failures = consecutive_failures + 1,
                       updated_at = now()
                 WHERE id = %s
                """,
                (state, error_code, (error_detail or "")[:500], source_id),
            )
        else:
            cursor.execute(
                """
                UPDATE source SET runtime_state = %s, last_success_at = now(),
                       last_error_code = NULL, last_error_detail = NULL,
                       consecutive_failures = 0, updated_at = now()
                 WHERE id = %s
                """,
                (state, source_id),
            )


def record_source_failure(
    connection: Any,
    source_id: str,
    *,
    error_code: str,
    error_detail: str,
    retryable: bool,
) -> str:
    """Advance the failure ladder of AHR-SOURCE-900 §5 and return the new state.

    The decision needs the row as it stands before the increment — the failure
    count, the last success, and the verdict the source currently holds — so it
    is read here and handed to `health.next_state_after_failure`, which is where
    the rule lives and where it is tested.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT runtime_state, consecutive_failures, last_success_at, created_at, now()
              FROM source WHERE id = %s FOR UPDATE
            """,
            (source_id,),
        )
        row = cursor.fetchone()

    if row is None:
        # Nothing to demote. The caller still reports the error.
        return "QUARANTINED"

    state = next_state_after_failure(
        current_state=str(row[0]),
        error_code=error_code,
        retryable=retryable,
        consecutive_failures=int(row[1] or 0),
        last_success_at=row[2],
        created_at=row[3],
        now=row[4],
    )
    update_source_state(
        connection, source_id, state=state, error_code=error_code, error_detail=error_detail
    )
    return state

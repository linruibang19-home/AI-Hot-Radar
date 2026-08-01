-- M1 ingestion runtime support (TASK-M1-001).
--
-- V001 assumed every source declares a literal discovery_url. ADR-0012 records
-- that 64 of 140 sources derive their endpoint from a template instead
-- ({repository} for GitHub, {subject} for arXiv), so the column must be
-- nullable and the template inputs need a home.

ALTER TABLE source ALTER COLUMN discovery_url DROP NOT NULL;

-- arXiv feeds are addressed by subject code (cs.AI, cs.CL, ...).
ALTER TABLE source ADD COLUMN IF NOT EXISTS subject VARCHAR(40);

-- A source must be reachable by exactly one of: literal URL, repository slug,
-- or arXiv subject. This keeps the database honest even if the loader regresses.
ALTER TABLE source ADD CONSTRAINT ck_source_endpoint_present CHECK (
    discovery_url IS NOT NULL OR repository IS NOT NULL OR subject IS NOT NULL
);

-- AHR-SOURCE-900 §8 acceptance reporting needs to distinguish "we fetched
-- metadata" from "we obtained real fulltext".
ALTER TABLE source ADD COLUMN IF NOT EXISTS content_access VARCHAR(40);
ALTER TABLE source ADD COLUMN IF NOT EXISTS public_render VARCHAR(40) NOT NULL DEFAULT 'excerpt_link';
ALTER TABLE source ADD COLUMN IF NOT EXISTS poll_interval_seconds INTEGER NOT NULL DEFAULT 1800;
ALTER TABLE source ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_source_poll
    ON source (next_poll_at)
    WHERE runtime_state IN ('CONFIGURED', 'PROBING', 'ACTIVE', 'DEGRADED');

-- AHR-ARCH-200 §4: every stage records its own status, attempt count and
-- error so a failed document can be located and safely retried.
ALTER TABLE raw_document ADD COLUMN IF NOT EXISTS processing_status VARCHAR(24) NOT NULL DEFAULT 'DISCOVERED';
ALTER TABLE raw_document ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE raw_document ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(80);
ALTER TABLE raw_document ADD COLUMN IF NOT EXISTS last_error_detail TEXT;
ALTER TABLE raw_document ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE raw_document ADD COLUMN IF NOT EXISTS discovery_summary TEXT;

ALTER TABLE raw_document ADD CONSTRAINT ck_raw_document_status CHECK (
    processing_status IN (
        'DISCOVERED', 'FETCHED', 'PARSED', 'ENRICHED', 'DEDUPED',
        'CLUSTERED', 'INDEXED', 'PUBLISHED',
        'RETRYABLE_FAILED', 'DEAD_LETTER', 'BLOCKED_POLICY', 'DELETED'
    )
);

CREATE INDEX IF NOT EXISTS idx_raw_document_status
    ON raw_document (processing_status, next_retry_at);

-- The UNIQUE (source_id, body_sha256) constraint from V001 would collide the
-- moment two fetches of the same source return identical bytes, which happens
-- routinely for changelog pages that have not changed. Idempotency is already
-- guaranteed by (source_id, external_id); byte-identical bodies are expected.
ALTER TABLE raw_document DROP CONSTRAINT IF EXISTS raw_document_source_id_body_sha256_key;
CREATE INDEX IF NOT EXISTS idx_raw_document_body_sha ON raw_document (source_id, body_sha256);

-- AHR-ARCH-200 §6: workers record processed event ids so a redelivered event
-- is acknowledged instead of applied twice.
CREATE TABLE IF NOT EXISTS processed_event (
    event_id        UUID PRIMARY KEY,
    consumer        VARCHAR(80) NOT NULL,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    result          VARCHAR(24) NOT NULL
);

-- Per-source fulltext outcome, so source-health.json can report the
-- fulltext_parse_success_rate that AHR-SOURCE-900 §8 requires without
-- recomputing it from raw bodies.
CREATE TABLE IF NOT EXISTS fulltext_attempt (
    id                  UUID PRIMARY KEY,
    source_id           VARCHAR(80) NOT NULL REFERENCES source(id),
    raw_document_id     UUID REFERENCES raw_document(id),
    canonical_url       TEXT,
    decision            VARCHAR(24) NOT NULL,
    reason_code         VARCHAR(80),
    body_chars          INTEGER NOT NULL DEFAULT 0,
    paragraph_count     INTEGER NOT NULL DEFAULT 0,
    link_density        NUMERIC(6,5),
    extractor           VARCHAR(60),
    attempted_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fulltext_attempt_source
    ON fulltext_attempt (source_id, attempted_at DESC);

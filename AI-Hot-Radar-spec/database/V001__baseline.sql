CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE source (
    id                  VARCHAR(80) PRIMARY KEY,
    name                VARCHAR(200) NOT NULL,
    organization        VARCHAR(200) NOT NULL,
    source_group        VARCHAR(80) NOT NULL,
    region              VARCHAR(20) NOT NULL,
    source_tier         VARCHAR(40) NOT NULL,
    priority            VARCHAR(4) NOT NULL,
    profile             VARCHAR(80) NOT NULL,
    homepage_url        TEXT,
    discovery_url       TEXT NOT NULL,
    repository          VARCHAR(240),
    content_access      VARCHAR(40) NOT NULL,
    verification        VARCHAR(40) NOT NULL,
    configured_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
    runtime_state       VARCHAR(24) NOT NULL DEFAULT 'CONFIGURED',
    config_version      VARCHAR(40) NOT NULL,
    next_poll_at        TIMESTAMPTZ,
    last_success_at     TIMESTAMPTZ,
    last_error_code     VARCHAR(80),
    last_error_detail   TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_source_state CHECK (runtime_state IN ('CONFIGURED','PROBING','ACTIVE','DEGRADED','QUARANTINED','DISABLED'))
);

CREATE TABLE source_cursor (
    source_id           VARCHAR(80) PRIMARY KEY REFERENCES source(id),
    cursor_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    etag                TEXT,
    last_modified       TEXT,
    lease_owner         VARCHAR(160),
    lease_until         TIMESTAMPTZ,
    version             BIGINT NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE crawl_run (
    id                  UUID PRIMARY KEY,
    source_id           VARCHAR(80) NOT NULL REFERENCES source(id),
    trigger_type        VARCHAR(24) NOT NULL,
    status              VARCHAR(24) NOT NULL,
    cursor_before       JSONB NOT NULL DEFAULT '{}'::jsonb,
    cursor_after        JSONB,
    discovered_count    INTEGER NOT NULL DEFAULT 0,
    fetched_count       INTEGER NOT NULL DEFAULT 0,
    accepted_count      INTEGER NOT NULL DEFAULT 0,
    rejected_count      INTEGER NOT NULL DEFAULT 0,
    http_status         INTEGER,
    error_code          VARCHAR(80),
    error_detail        TEXT,
    trace_id            VARCHAR(64) NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ
);
CREATE INDEX idx_crawl_run_source_started ON crawl_run(source_id, started_at DESC);

CREATE TABLE ingestion_task (
    id                  UUID PRIMARY KEY,
    task_type           VARCHAR(40) NOT NULL,
    source_id           VARCHAR(80) REFERENCES source(id),
    aggregate_id        UUID,
    input_version       BIGINT NOT NULL DEFAULT 1,
    status              VARCHAR(24) NOT NULL DEFAULT 'PENDING',
    attempt             INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 3,
    available_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_owner         VARCHAR(160),
    lease_until         TIMESTAMPTZ,
    idempotency_key     VARCHAR(240) NOT NULL,
    payload             JSONB NOT NULL,
    result              JSONB,
    error_code          VARCHAR(80),
    error_detail        TEXT,
    trace_id            VARCHAR(64) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (idempotency_key)
);
CREATE INDEX idx_task_claim ON ingestion_task(status, available_at) WHERE status IN ('PENDING','RETRY');

CREATE TABLE raw_document (
    id                  UUID PRIMARY KEY,
    source_id           VARCHAR(80) NOT NULL REFERENCES source(id),
    crawl_run_id        UUID REFERENCES crawl_run(id),
    external_id         TEXT,
    requested_url       TEXT NOT NULL,
    final_url           TEXT,
    canonical_url       TEXT,
    canonical_url_hash  CHAR(64),
    http_status         INTEGER,
    response_headers    JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_type        VARCHAR(160),
    body_bytes          BYTEA,
    body_sha256         CHAR(64),
    fetched_at          TIMESTAMPTZ NOT NULL,
    parser_version      VARCHAR(80),
    expires_at          TIMESTAMPTZ,
    UNIQUE (source_id, external_id),
    UNIQUE (source_id, body_sha256)
);
CREATE INDEX idx_raw_canonical_hash ON raw_document(canonical_url_hash);

CREATE TABLE content_item (
    id                  UUID PRIMARY KEY,
    source_id           VARCHAR(80) NOT NULL REFERENCES source(id),
    external_id         TEXT,
    canonical_url       TEXT NOT NULL,
    canonical_url_hash  CHAR(64) NOT NULL,
    item_type           VARCHAR(40) NOT NULL,
    language            VARCHAR(16),
    title               TEXT NOT NULL,
    published_at        TIMESTAMPTZ,
    observed_at         TIMESTAMPTZ NOT NULL,
    current_revision_id UUID,
    workflow_state      VARCHAR(24) NOT NULL DEFAULT 'DISCOVERED',
    public_render       VARCHAR(40) NOT NULL DEFAULT 'excerpt_link',
    source_tier         VARCHAR(40) NOT NULL,
    attributes          JSONB NOT NULL DEFAULT '{}'::jsonb,
    version             BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, external_id),
    UNIQUE (canonical_url_hash)
);
CREATE INDEX idx_item_published ON content_item(published_at DESC, id DESC);
CREATE INDEX idx_item_state ON content_item(workflow_state, published_at DESC);

CREATE TABLE content_revision (
    id                  UUID PRIMARY KEY,
    content_item_id     UUID NOT NULL REFERENCES content_item(id),
    raw_document_id     UUID REFERENCES raw_document(id),
    revision_no         INTEGER NOT NULL,
    title               TEXT NOT NULL,
    body_markdown       TEXT,
    body_text           TEXT NOT NULL,
    excerpt             TEXT,
    discovery_summary   TEXT,
    content_sha256      CHAR(64) NOT NULL,
    extraction_method   VARCHAR(80) NOT NULL,
    extraction_version  VARCHAR(80) NOT NULL,
    quality_score       NUMERIC(5,4) NOT NULL,
    quality_decision    VARCHAR(24) NOT NULL,
    quality_reasons     JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_item_id, revision_no),
    UNIQUE (content_item_id, content_sha256)
);
ALTER TABLE content_item ADD CONSTRAINT fk_item_current_revision
    FOREIGN KEY (current_revision_id) REFERENCES content_revision(id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE content_chunk (
    id                  UUID PRIMARY KEY,
    content_revision_id UUID NOT NULL REFERENCES content_revision(id),
    ordinal             INTEGER NOT NULL,
    heading_path        TEXT[],
    body_text           TEXT NOT NULL,
    token_count         INTEGER NOT NULL,
    char_start          INTEGER,
    char_end            INTEGER,
    page_no             INTEGER,
    search_vector       TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', coalesce(body_text,''))) STORED,
    embedding           VECTOR(1536),
    embedding_model     VARCHAR(120),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_revision_id, ordinal)
);
CREATE INDEX idx_chunk_fts ON content_chunk USING GIN(search_vector);
CREATE INDEX idx_chunk_revision ON content_chunk(content_revision_id, ordinal);

CREATE TABLE story (
    id                  UUID PRIMARY KEY,
    slug                VARCHAR(240) UNIQUE,
    title               TEXT NOT NULL,
    summary             TEXT,
    occurred_at         TIMESTAMPTZ,
    first_seen_at       TIMESTAMPTZ NOT NULL,
    last_updated_at     TIMESTAMPTZ NOT NULL,
    primary_item_id     UUID REFERENCES content_item(id),
    status              VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
    locked_by_editor    BOOLEAN NOT NULL DEFAULT FALSE,
    heat_score          NUMERIC(10,4),
    version             BIGINT NOT NULL DEFAULT 1,
    attributes          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE story_item (
    story_id            UUID NOT NULL REFERENCES story(id),
    content_item_id     UUID NOT NULL REFERENCES content_item(id),
    relation_type       VARCHAR(24) NOT NULL DEFAULT 'SUPPORTS',
    independent_source  BOOLEAN NOT NULL DEFAULT TRUE,
    similarity_score    NUMERIC(6,5),
    added_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (story_id, content_item_id)
);

CREATE TABLE topic (
    id                  UUID PRIMARY KEY,
    slug                VARCHAR(120) UNIQUE NOT NULL,
    name                CITEXT NOT NULL,
    parent_id           UUID REFERENCES topic(id)
);
CREATE TABLE story_topic (
    story_id UUID NOT NULL REFERENCES story(id),
    topic_id UUID NOT NULL REFERENCES topic(id),
    score NUMERIC(6,5),
    PRIMARY KEY (story_id, topic_id)
);

CREATE TABLE report (
    id                  UUID PRIMARY KEY,
    period_type         VARCHAR(16) NOT NULL,
    period_key          VARCHAR(32) NOT NULL,
    title               TEXT NOT NULL,
    body_markdown       TEXT NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
    generated_at        TIMESTAMPTZ NOT NULL,
    published_at        TIMESTAMPTZ,
    generation_meta     JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (period_type, period_key)
);

CREATE TABLE outbox_event (
    id                  UUID PRIMARY KEY,
    aggregate_type      VARCHAR(40) NOT NULL,
    aggregate_id        UUID NOT NULL,
    event_type          VARCHAR(80) NOT NULL,
    payload             JSONB NOT NULL,
    trace_id            VARCHAR(64) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at        TIMESTAMPTZ,
    attempts            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_outbox_pending ON outbox_event(created_at) WHERE published_at IS NULL;

CREATE TABLE rag_query (
    id                  UUID PRIMARY KEY,
    conversation_id     UUID,
    question            TEXT NOT NULL,
    retrieval_plan      JSONB,
    answer_markdown     TEXT,
    status              VARCHAR(24) NOT NULL,
    model_meta          JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

CREATE TABLE rag_citation (
    rag_query_id        UUID NOT NULL REFERENCES rag_query(id),
    citation_no         INTEGER NOT NULL,
    content_chunk_id    UUID NOT NULL REFERENCES content_chunk(id),
    claim_text          TEXT NOT NULL,
    support_score       NUMERIC(6,5),
    PRIMARY KEY (rag_query_id, citation_no)
);

CREATE TABLE source_health_daily (
    source_id                       VARCHAR(80) NOT NULL REFERENCES source(id),
    day                             DATE NOT NULL,
    discovery_success_rate          NUMERIC(6,5),
    article_fetch_success_rate      NUMERIC(6,5),
    fulltext_parse_success_rate     NUMERIC(6,5),
    median_body_chars               INTEGER,
    freshness_lag_p95_seconds       BIGINT,
    duplicate_rate                  NUMERIC(6,5),
    canonical_resolution_rate       NUMERIC(6,5),
    metrics                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (source_id, day)
);


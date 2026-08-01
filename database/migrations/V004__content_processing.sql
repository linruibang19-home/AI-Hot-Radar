-- M2 content processing support (TASK-M2-001).

-- Near-duplicate detection (AHR-DATA-300 §5 layer 2). Stored as BIGINT because
-- PostgreSQL has no unsigned 64-bit type; the application maps the SimHash into
-- signed range. This is deliberately separate from content_sha256, which only
-- catches byte-identical bodies.
ALTER TABLE content_revision ADD COLUMN IF NOT EXISTS simhash BIGINT;
CREATE INDEX IF NOT EXISTS idx_revision_simhash ON content_revision (simhash)
    WHERE simhash IS NOT NULL;

-- A near-duplicate is recorded, never silently dropped: the copy still counts
-- as an independent source signal for Story heat in M3.
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS duplicate_of_id UUID REFERENCES content_item(id);
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS duplicate_kind VARCHAR(24);
ALTER TABLE content_item ADD CONSTRAINT ck_item_duplicate_kind CHECK (
    duplicate_kind IS NULL OR duplicate_kind IN ('EXACT', 'NEAR')
);
CREATE INDEX IF NOT EXISTS idx_item_duplicate_of ON content_item (duplicate_of_id)
    WHERE duplicate_of_id IS NOT NULL;

-- AI enrichment output (AHR-DATA-300 §7). Kept on content_item so a failed
-- enrichment leaves the article readable rather than blocking the site.
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS summary_zh TEXT;
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS zh_title TEXT;
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS content_type VARCHAR(40);
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS quality_score NUMERIC(5,2);
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS enrichment_state VARCHAR(24) NOT NULL DEFAULT 'PENDING';
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS enrichment_error TEXT;
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(40);
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS model_name VARCHAR(80);
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ;

ALTER TABLE content_item ADD CONSTRAINT ck_item_enrichment_state CHECK (
    enrichment_state IN ('PENDING', 'IN_PROGRESS', 'ENRICHED', 'FAILED', 'DEAD_LETTER', 'SKIPPED')
);

CREATE INDEX IF NOT EXISTS idx_item_enrichment ON content_item (enrichment_state)
    WHERE enrichment_state IN ('PENDING', 'FAILED');

-- Feed and selection queries read published content newest-first.
CREATE INDEX IF NOT EXISTS idx_item_feed
    ON content_item (published_at DESC NULLS LAST, id DESC)
    WHERE duplicate_of_id IS NULL;

-- Entities and topics extracted by the LLM, normalised against the alias
-- dictionary before insert (AHR-DATA-300 §7).
CREATE TABLE IF NOT EXISTS entity (
    id              UUID PRIMARY KEY,
    slug            VARCHAR(160) UNIQUE NOT NULL,
    name            VARCHAR(200) NOT NULL,
    entity_type     VARCHAR(24) NOT NULL,
    aliases         JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_entity_type CHECK (
        entity_type IN ('company', 'product', 'model', 'technology', 'person')
    )
);

CREATE TABLE IF NOT EXISTS item_entity (
    content_item_id UUID NOT NULL REFERENCES content_item(id) ON DELETE CASCADE,
    entity_id       UUID NOT NULL REFERENCES entity(id),
    role            VARCHAR(16) NOT NULL DEFAULT 'mention',
    confidence      NUMERIC(4,3),
    PRIMARY KEY (content_item_id, entity_id),
    CONSTRAINT ck_item_entity_role CHECK (role IN ('subject', 'object', 'mention'))
);
CREATE INDEX IF NOT EXISTS idx_item_entity_reverse ON item_entity (entity_id, content_item_id);

CREATE TABLE IF NOT EXISTS item_topic (
    content_item_id UUID NOT NULL REFERENCES content_item(id) ON DELETE CASCADE,
    topic_id        UUID NOT NULL REFERENCES topic(id),
    confidence      NUMERIC(4,3),
    PRIMARY KEY (content_item_id, topic_id)
);
CREATE INDEX IF NOT EXISTS idx_item_topic_reverse ON item_topic (topic_id, content_item_id);

-- Chunks are rebuilt when a revision changes, so cascade keeps them consistent.
ALTER TABLE content_chunk DROP CONSTRAINT IF EXISTS content_chunk_content_revision_id_fkey;
ALTER TABLE content_chunk ADD CONSTRAINT content_chunk_content_revision_id_fkey
    FOREIGN KEY (content_revision_id) REFERENCES content_revision(id) ON DELETE CASCADE;

-- Story clustering (M3).
--
-- `story` and `story_item` come from the V001 baseline; this adds what the
-- clustering pass needs to be auditable and re-runnable.

-- Provenance for every automatic decision. AHR-SPEC-000 §8 requires the
-- algorithm version to be recorded so a re-cluster can be compared against the
-- previous run rather than silently replacing it.
ALTER TABLE story ADD COLUMN IF NOT EXISTS algorithm_version VARCHAR(40);
ALTER TABLE story ADD COLUMN IF NOT EXISTS clustered_at TIMESTAMPTZ;

-- Denormalised because the hot list orders by it and the count is read far more
-- often than story membership changes.
ALTER TABLE story ADD COLUMN IF NOT EXISTS independent_source_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE story ADD COLUMN IF NOT EXISTS item_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_story_heat
    ON story (heat_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_story_occurred
    ON story (occurred_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_story_item_item
    ON story_item (content_item_id);

-- The per-pair score that put an item in a story, kept so a bad merge can be
-- explained instead of just reverted.
ALTER TABLE story_item ADD COLUMN IF NOT EXISTS score_breakdown JSONB;

-- AHR-DATA-300 §8: "高风险自动合并先进入 cluster_suggestion". A merge that the
-- score supports but a hard rule is unsure about is written here for review
-- rather than applied, so an incorrect merge never reaches the site silently.
CREATE TABLE IF NOT EXISTS cluster_suggestion (
    id                  UUID PRIMARY KEY,
    left_item_id        UUID NOT NULL REFERENCES content_item(id),
    right_item_id       UUID NOT NULL REFERENCES content_item(id),
    score               NUMERIC(6,5) NOT NULL,
    score_breakdown     JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason              TEXT NOT NULL,
    algorithm_version   VARCHAR(40) NOT NULL,
    status              VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    CONSTRAINT ck_suggestion_status CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED')),
    -- Item order is normalised by the writer so the same pair cannot be
    -- suggested twice under two orderings.
    CONSTRAINT uq_suggestion_pair UNIQUE (left_item_id, right_item_id)
);

CREATE INDEX IF NOT EXISTS idx_suggestion_pending
    ON cluster_suggestion (created_at DESC) WHERE status = 'PENDING';

-- Graph-lite edges between stories (docs/spec/03 §5). Populated from M3 onward;
-- the relation vocabulary is fixed by config/taxonomy.yaml.
CREATE TABLE IF NOT EXISTS story_relation (
    from_story_id       UUID NOT NULL REFERENCES story(id),
    to_story_id         UUID NOT NULL REFERENCES story(id),
    relation_type       VARCHAR(24) NOT NULL,
    confidence          NUMERIC(6,5),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (from_story_id, to_story_id, relation_type),
    CONSTRAINT ck_story_relation_self CHECK (from_story_id <> to_story_id)
);

-- Link items back to their story so the feed can show corroboration without a
-- join through story_item on every row.
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS story_id UUID REFERENCES story(id);
CREATE INDEX IF NOT EXISTS idx_item_story ON content_item (story_id);

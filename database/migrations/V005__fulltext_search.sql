-- Keyword search over content (TASK-M2-002).
--
-- AHR-PRD-100 §102 is explicit that exact product names, version numbers and
-- abbreviations must not depend on vector search alone, so keyword retrieval is
-- a first-class channel here and later feeds the RRF fusion in M4
-- (AHR-RAG-400 §5 KEYWORD_FTS).
--
-- The 'simple' configuration is used rather than 'english': the corpus is
-- mixed Chinese and English, and English stemming would mangle version strings
-- like "v2.52.0" while doing nothing useful for Chinese.

ALTER TABLE content_item ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        -- Weights follow AHR-DATA-300 §3: title A, summary B.
        setweight(to_tsvector('simple', coalesce(title, '')), 'A')
        || setweight(to_tsvector('simple', coalesce(zh_title, '')), 'A')
        || setweight(to_tsvector('simple', coalesce(summary_zh, '')), 'B')
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_item_search ON content_item USING GIN (search_vector);

-- Trigram index backs substring matching for partial version strings and
-- model names that tsvector tokenisation splits apart.
CREATE INDEX IF NOT EXISTS idx_item_title_trgm
    ON content_item USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_item_zh_title_trgm
    ON content_item USING GIN (zh_title gin_trgm_ops);

-- Editorial selection (AHR-FEAT-101). Kept as its own table so a curation
-- decision is auditable and reversible without mutating the content row.
CREATE TABLE IF NOT EXISTS selection_record (
    id                UUID PRIMARY KEY,
    content_item_id   UUID NOT NULL REFERENCES content_item(id) ON DELETE CASCADE,
    selected_for_date DATE NOT NULL,
    score             NUMERIC(6,2) NOT NULL,
    reason            TEXT,
    factors           JSONB NOT NULL DEFAULT '{}'::jsonb,
    algorithm_version VARCHAR(40) NOT NULL,
    selected_by       VARCHAR(40) NOT NULL DEFAULT 'auto',
    withdrawn_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One decision per item per day; re-running the selector updates in place.
    UNIQUE (content_item_id, selected_for_date)
);

CREATE INDEX IF NOT EXISTS idx_selection_date
    ON selection_record (selected_for_date DESC, score DESC)
    WHERE withdrawn_at IS NULL;

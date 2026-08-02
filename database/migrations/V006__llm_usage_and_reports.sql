-- LLM cost accounting and report storage (TASK-M2-003).

-- AHR-QSO-700 §5 requires token_in / token_out / cost_estimate to be
-- observable. Without a record of actual usage, spend can only be guessed from
-- character counts, which ignores tokenisation and prompt caching entirely.
CREATE TABLE IF NOT EXISTS llm_usage (
    id                  UUID PRIMARY KEY,
    content_item_id     UUID REFERENCES content_item(id) ON DELETE SET NULL,
    operation           VARCHAR(40) NOT NULL,
    model               VARCHAR(80) NOT NULL,
    prompt_version      VARCHAR(40),
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    -- Providers bill cached prompt tokens at a lower rate, so they are tracked
    -- separately rather than folded into prompt_tokens.
    cached_tokens       INTEGER NOT NULL DEFAULT 0,
    attempts            INTEGER NOT NULL DEFAULT 1,
    succeeded           BOOLEAN NOT NULL DEFAULT TRUE,
    latency_ms          INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage (model, created_at DESC);

-- Daily/weekly/monthly reports. AHR-FEAT-105 requires a report to be generated
-- from published stories rather than by concatenating articles, and to record
-- the versions it was produced with so it stays reproducible.
ALTER TABLE report ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE report ADD COLUMN IF NOT EXISTS item_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE report ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(40);
ALTER TABLE report ADD COLUMN IF NOT EXISTS model_name VARCHAR(80);

-- Which items a report was built from, so every claim in it is traceable back
-- to a source (AHR-SPEC-000 §7 forbids presenting generated text as fact
-- without provenance).
CREATE TABLE IF NOT EXISTS report_item (
    report_id       UUID NOT NULL REFERENCES report(id) ON DELETE CASCADE,
    content_item_id UUID NOT NULL REFERENCES content_item(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    section         VARCHAR(60),
    PRIMARY KEY (report_id, content_item_id)
);

CREATE INDEX IF NOT EXISTS idx_report_item_order ON report_item (report_id, position);

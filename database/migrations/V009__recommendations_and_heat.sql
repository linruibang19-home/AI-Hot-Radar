-- LLM recommendation reasons, heat ranking and multi-period reports.

-- The first selection reason was assembled from the top-scoring factors, which
-- produced the same sentence for nearly every item. Reasons are now written per
-- item by the model, so the version and model are recorded alongside the text
-- (AHR-SPEC-000 §8 requires prompt and model versions to be traceable).
ALTER TABLE selection_record ADD COLUMN IF NOT EXISTS reason_version VARCHAR(40);
ALTER TABLE selection_record ADD COLUMN IF NOT EXISTS reason_model VARCHAR(80);

-- Heat ranking for the homepage list. AHR-PRD-100 §4 keeps hot_score separate
-- from quality_score: quality judges one article, heat measures how much
-- attention an event is currently drawing and decays with time.
--
-- Pre-M3 this ranks content_items directly. Once Story clustering exists the
-- same column moves to story, which is why independent_source_count is here
-- from the start rather than being bolted on later.
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS hot_score NUMERIC(8,3);
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS hot_scored_at TIMESTAMPTZ;
ALTER TABLE content_item ADD COLUMN IF NOT EXISTS independent_source_count INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_item_hot
    ON content_item (hot_score DESC NULLS LAST)
    WHERE duplicate_of_id IS NULL;

-- Reports already carry period_type; widen the allowed values so weekly and
-- monthly digests share the same table and rendering path as the daily one.
ALTER TABLE report DROP CONSTRAINT IF EXISTS ck_report_period_type;
ALTER TABLE report ADD CONSTRAINT ck_report_period_type CHECK (
    period_type IN ('daily', 'weekly', 'monthly')
);

CREATE INDEX IF NOT EXISTS idx_report_period
    ON report (period_type, period_key DESC);

-- Topic grouping for the topic map. The taxonomy already nests children under
-- parents; this adds the display metadata the page needs without inventing a
-- second hierarchy.
ALTER TABLE topic ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE topic ADD COLUMN IF NOT EXISTS display_group VARCHAR(40);
ALTER TABLE topic ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 100;

CREATE INDEX IF NOT EXISTS idx_topic_group ON topic (display_group, display_order);

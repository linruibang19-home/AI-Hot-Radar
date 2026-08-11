-- TASK-M5-007 / ADR-0027: auditable DeepSeek generation-model selection.

CREATE TABLE generation_model_catalog (
    model_id                       VARCHAR(80) PRIMARY KEY,
    display_name                   VARCHAR(120) NOT NULL,
    description                    TEXT NOT NULL,
    context_window_tokens          INTEGER NOT NULL CHECK (context_window_tokens > 0),
    input_cny_per_million          NUMERIC(12,6) NOT NULL CHECK (input_cny_per_million >= 0),
    cached_input_cny_per_million   NUMERIC(12,6) NOT NULL CHECK (cached_input_cny_per_million >= 0),
    output_cny_per_million         NUMERIC(12,6) NOT NULL CHECK (output_cny_per_million >= 0),
    pricing_effective_on           DATE NOT NULL,
    pricing_source                 TEXT NOT NULL,
    enabled                        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO generation_model_catalog (
    model_id, display_name, description, context_window_tokens,
    input_cny_per_million, cached_input_cny_per_million, output_cny_per_million,
    pricing_effective_on, pricing_source
) VALUES
    ('deepseek-v4-flash', 'DeepSeek V4 Flash',
     '低成本、低延迟，适合高频内容整理与常规问答。', 1000000,
     1.000000, 0.020000, 2.000000, DATE '2026-08-11',
     'https://api-docs.deepseek.com/quick_start/pricing/'),
    ('deepseek-v4-pro', 'DeepSeek V4 Pro',
     '更高质量档位，适合比较复杂问题与高价值报告。', 1000000,
     3.000000, 0.025000, 6.000000, DATE '2026-08-11',
     'https://api-docs.deepseek.com/quick_start/pricing/')
ON CONFLICT (model_id) DO NOTHING;

CREATE TABLE generation_model_config (
    singleton_key      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (singleton_key = 1),
    model_id           VARCHAR(80) NOT NULL REFERENCES generation_model_catalog(model_id),
    version            INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_by         UUID REFERENCES admin_principal(id) ON DELETE SET NULL,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO generation_model_config (singleton_key, model_id)
VALUES (1, 'deepseek-v4-flash')
ON CONFLICT (singleton_key) DO NOTHING;

ALTER TABLE llm_usage
    ADD COLUMN IF NOT EXISTS model_config_version INTEGER,
    ADD COLUMN IF NOT EXISTS input_cny_per_million NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS cached_input_cny_per_million NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS output_cny_per_million NUMERIC(12,6);

COMMENT ON TABLE generation_model_config IS
    'Singleton DeepSeek generation model applied to future LLM work only; PostgreSQL is source of truth.';
COMMENT ON COLUMN llm_usage.model_config_version IS
    'Generation model configuration version at call creation time; NULL for pre-V024 rows.';

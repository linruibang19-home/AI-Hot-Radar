-- V018 adds curated vendor_entity rows, but a clean database has not run the
-- runtime `seed-topics` command yet and therefore has no vendor parents.
--
-- This migration deliberately sits between V017 (which creates the tables)
-- and V018 (which adds members). Existing databases already at V021 apply it
-- out of order; DO NOTHING preserves the richer taxonomy-managed rows there.

INSERT INTO vendor (slug, name, display_order) VALUES
    ('openai', 'OpenAI / ChatGPT', 0),
    ('anthropic', 'Anthropic / Claude', 1),
    ('google', 'Google / Gemini', 2),
    ('deepseek', 'DeepSeek', 3),
    ('qwen', '通义千问 Qwen', 4),
    ('kimi', 'Kimi / 月之暗面', 5),
    ('zhipu', '智谱 GLM', 7),
    ('microsoft', 'Microsoft / Copilot', 10)
ON CONFLICT (slug) DO NOTHING;

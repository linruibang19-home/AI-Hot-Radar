-- Fill the gaps in the curated vendor→entity map that query expansion depends on.
--
-- V017 built `vendor_entity` for the topic-map cards, where a missing row costs
-- a card an item and nothing else. RAG query expansion now reads the same map,
-- and there a missing row costs an answer.
--
-- Measured: asked 「智谱最近发布了什么？」 the system answered **「智谱没有发布任何
-- 新模型或产品更新」** while the seven-day window held three Zhipu items — the
-- one titled 「GLM-5.2 量化模型发布」 never contains the string 智谱, and keyword
-- retrieval matches strings. Expansion would have found it, except that the
-- entity `智谱` was in no vendor group: the group held `Zhipu`, `GLM`, `GLM-4.6`
-- and `GLM 5.2`, and not the Chinese name a Chinese speaker actually types.
--
-- For a product whose claim is verifiability, asserting that nothing happened is
-- worse than a hallucination, and this row is most of the cause.
--
-- Every entry below is a name already present in `entity`, extracted from the
-- corpus under whatever form appeared. Curation stays manual by design (V017's
-- comment explains why): entity rows are `deepseek` and `deepseek-v4` and
-- `deepseek-v4-flash-0731`, and no rule separates a product line from a version
-- without knowing the product.
--
-- Still incomplete after this, and visibly so: `llama.cpp` (100 items), `vLLM`,
-- `Cloudflare`, `Together AI` and `Ollama` belong to no vendor. They expand to
-- nothing and behave exactly as before — expansion helps where the map is
-- filled in and is inert everywhere else, so no query gets worse for a row that
-- is still missing.

INSERT INTO vendor_entity (vendor_slug, entity_slug) VALUES
    -- The row the measured failure needed, plus the other forms of the name.
    ('zhipu', '智谱'),
    ('zhipu', '智谱ai'),
    ('zhipu', 'zhipuai'),
    ('zhipu', 'glm-4.5'),
    ('zhipu', 'glm-4.7'),
    ('zhipu', 'glm-5'),
    ('zhipu', 'glm-5.1'),

    -- Chinese names of vendors whose groups held only the Latin ones. Same
    -- shape of gap as 智谱 and the same consequence.
    ('qwen', '阿里'),
    ('qwen', '阿里巴巴'),
    ('qwen', 'qwen3.8-max'),
    ('kimi', '月之暗面'),

    -- Version rows that a question names directly ("Claude Opus 4.8 有什么变化")
    -- and that carry real corpus weight: 16, 16, 15, 14 items respectively.
    ('anthropic', 'claude-api'),
    ('anthropic', 'claude.ai'),
    ('anthropic', 'claude-cowork'),
    ('anthropic', 'claude-opus-4.7'),
    ('anthropic', 'claude-opus-4.8'),
    ('openai', 'gpt-4o'),
    ('openai', 'gpt-5.4'),
    ('openai', 'gpt-5.6-luna'),
    ('deepseek', 'deepseek-v4-flash-0731'),
    ('deepseek', 'deepseek-v4-flash-preview'),
    ('deepseek', 'deepseek-v4-pro'),
    ('google', 'google-cloud'),
    ('microsoft', 'microsoft-research')
ON CONFLICT (vendor_slug, entity_slug) DO NOTHING;

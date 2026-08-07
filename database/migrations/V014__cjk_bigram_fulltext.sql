-- Make the keyword channel work in Chinese (ADR-0018).
--
-- Postgres' `simple` configuration splits on whitespace and punctuation, which
-- Chinese does not use between words. A whole run becomes one lexeme:
--
--     to_tsvector('simple', '智谱发布新模型 GLM-5')
--       -> '-5':3 'glm':2 '智谱发布新模型':1
--
--     ... @@ plainto_tsquery('simple', '智谱')   -> false
--     ... @@ plainto_tsquery('simple', 'GLM-5')  -> true
--
-- So the channel worked for ASCII model names and did nothing for Chinese. B2
-- measured the size of that: Recall@20 of 0.5798 on questions containing an
-- ASCII proper noun against **0.0588** on purely Chinese ones — a 52.1 point
-- gap, with all fifteen zero-hit questions Chinese.
--
-- **Character bigrams, not a segmenter.** `智谱发布` becomes `智谱 谱发 发布`,
-- so a query for `智谱` matches. It over-generates — `谱发` is not a word — but
-- the existing document-frequency filter already drops terms the corpus says
-- are common, and a meaningless bigram is by definition common or absent. That
-- filter was built to avoid a stop-word list; it turns out to handle this too.
--
-- Why not zhparser or pg_jieba: both need an extension compiled into the image,
-- and ADR-0015 already ruled that the sparse channel must not cost a new
-- component. This is one IMMUTABLE function.
--
-- The same function is used by the index *and* by the query builder, so the two
-- agree by construction — the property the previous design was careful to have
-- and which a Python-side segmenter would have quietly broken.

CREATE OR REPLACE FUNCTION ahr_cjk_bigrams(txt text) RETURNS text
    LANGUAGE sql
    IMMUTABLE
    STRICT
    PARALLEL SAFE
AS $$
    SELECT coalesce(string_agg(DISTINCT bigram, ' '), '')
      FROM (
            SELECT (regexp_matches(txt, '[一-鿿]{2,}', 'g'))[1] AS run
           ) runs,
           LATERAL generate_series(1, length(run) - 1) AS i,
           LATERAL (SELECT substr(run, i, 2) AS bigram) b
$$;

COMMENT ON FUNCTION ahr_cjk_bigrams(text) IS
    'Overlapping character bigrams for CJK runs of two or more characters. '
    'Used by both the stored search vectors and the query builder so that '
    'index and query tokenise identically.';

-- Rebuilding a generated column means dropping and re-adding it, which also
-- drops the index on it. Both are recreated below; at this corpus size the
-- rewrite takes seconds.
DROP INDEX IF EXISTS idx_chunk_fts;
ALTER TABLE content_chunk DROP COLUMN IF EXISTS search_vector;
ALTER TABLE content_chunk
    ADD COLUMN search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(body_text, ''))
        || to_tsvector('simple', ahr_cjk_bigrams(coalesce(body_text, '')))
    ) STORED;
CREATE INDEX idx_chunk_fts ON content_chunk USING GIN(search_vector);

-- The item-level vector feeds site search, which has the same problem: a reader
-- searching 智谱 got nothing while GLM-5 worked.
DROP INDEX IF EXISTS idx_item_search;
ALTER TABLE content_item DROP COLUMN IF EXISTS search_vector;
ALTER TABLE content_item
    ADD COLUMN search_vector TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(title, '')), 'A')
        || setweight(to_tsvector('simple', coalesce(zh_title, '')), 'A')
        || setweight(to_tsvector('simple', ahr_cjk_bigrams(coalesce(zh_title, ''))), 'A')
        || setweight(to_tsvector('simple', ahr_cjk_bigrams(coalesce(title, ''))), 'A')
        || setweight(to_tsvector('simple', coalesce(summary_zh, '')), 'B')
        || setweight(to_tsvector('simple', ahr_cjk_bigrams(coalesce(summary_zh, ''))), 'B')
    ) STORED;
CREATE INDEX idx_item_search ON content_item USING GIN(search_vector);

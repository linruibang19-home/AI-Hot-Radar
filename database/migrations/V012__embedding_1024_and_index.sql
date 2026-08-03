-- M4: switch the embedding column to the dimensionality we actually use, and
-- add the index that makes vector search viable.
--
-- The baseline reserved vector(1536), which was a guess at OpenAI's
-- text-embedding-3-small. The provider chosen is SiliconFlow and the model is
-- BAAI/bge-m3 at 1024 dimensions — picked because this corpus is genuinely
-- bilingual (Chinese titles and summaries over mostly English source bodies)
-- and bge-m3 is trained for multilingual retrieval rather than being an English
-- model that tolerates Chinese.
--
-- No embeddings exist yet (0 of 3831 chunks), so the column is altered rather
-- than migrated. If that stops being true this must become a rewrite: pgvector
-- cannot compare vectors of different dimensions, so a mixed column silently
-- breaks every query that touches it.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM content_chunk WHERE embedding IS NOT NULL) THEN
        RAISE EXCEPTION
            'content_chunk already holds embeddings; changing dimensionality '
            'requires re-embedding every row, not an ALTER';
    END IF;
END $$;

DROP INDEX IF EXISTS idx_chunk_embedding;
ALTER TABLE content_chunk ALTER COLUMN embedding TYPE vector(1024);

-- HNSW rather than IVFFlat. IVFFlat has to be built after the data exists and
-- rebuilt as the corpus grows, and its recall depends on a list count tuned to
-- a row count that changes hourly here. HNSW builds incrementally, so a chunk
-- written by the pipeline is searchable immediately.
--
-- Cosine distance because bge-m3 embeddings are normalised and cosine is what
-- the model was trained against.
CREATE INDEX IF NOT EXISTS idx_chunk_embedding
    ON content_chunk USING hnsw (embedding vector_cosine_ops);

-- Which model produced a vector. Without it, swapping models leaves a mix of
-- incomparable vectors with no way to tell them apart or re-embed selectively.
CREATE INDEX IF NOT EXISTS idx_chunk_embedding_model
    ON content_chunk (embedding_model)
    WHERE embedding IS NOT NULL;

-- Finding what still needs embedding is the pipeline's hottest query.
CREATE INDEX IF NOT EXISTS idx_chunk_pending_embedding
    ON content_chunk (id)
    WHERE embedding IS NULL;

COMMENT ON COLUMN content_chunk.embedding IS
    'bge-m3 (1024d), cosine. Dimensionality is pinned by V012; changing it '
    'requires re-embedding the whole table.';

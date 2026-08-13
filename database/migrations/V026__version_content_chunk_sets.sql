-- A cited physical chunk is immutable evidence (ADR-0029/0031). Re-chunking
-- retires a set and inserts a new one instead of deleting history.
ALTER TABLE content_chunk
    ADD COLUMN chunk_set_id UUID,
    ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE content_chunk
   SET chunk_set_id = content_revision_id
 WHERE chunk_set_id IS NULL;

ALTER TABLE content_chunk
    ALTER COLUMN chunk_set_id SET NOT NULL;

ALTER TABLE content_chunk
    DROP CONSTRAINT IF EXISTS content_chunk_content_revision_id_ordinal_key;

ALTER TABLE content_chunk
    ADD CONSTRAINT uq_content_chunk_set_ordinal UNIQUE (chunk_set_id, ordinal);

CREATE UNIQUE INDEX uq_content_chunk_active_revision_ordinal
    ON content_chunk (content_revision_id, ordinal)
    WHERE is_active;

CREATE INDEX idx_content_chunk_active_revision
    ON content_chunk (content_revision_id, ordinal)
    WHERE is_active;

CREATE INDEX idx_content_chunk_active_embedding
    ON content_chunk (created_at)
    WHERE is_active AND embedding IS NULL;

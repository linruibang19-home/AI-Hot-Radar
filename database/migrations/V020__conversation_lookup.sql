-- Make a conversation cheap to read back.
--
-- `conversation_id` has been a column since V001 and unindexed the whole time,
-- which cost nothing while nothing read it. Phase C made it the key of two hot
-- paths: `load_turns` runs on every follow-up before retrieval starts, and the
-- read-back route restores a thread after a reload. Both filter by
-- conversation and order by completion, and both were sequential scans.
--
-- Partial, because the overwhelming majority of rows have no conversation —
-- 185 of 190 at the time of writing. Indexing those would be paying to store
-- NULLs that no query in the system looks for.
CREATE INDEX IF NOT EXISTS rag_query_conversation_idx
    ON rag_query (conversation_id, completed_at DESC)
    WHERE conversation_id IS NOT NULL;

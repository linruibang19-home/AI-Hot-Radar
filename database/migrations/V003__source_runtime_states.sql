-- Widen the source runtime state machine (TASK-M1-001).
--
-- V001 allowed CONFIGURED/PROBING/ACTIVE/DEGRADED/QUARANTINED/DISABLED. Running
-- real sources showed two outcomes that fit none of those and were being forced
-- into misleading buckets:
--
--   METADATA_ONLY - discovery works and content is real, but the source only
--                   ever yields abstracts (OpenAlex) or short entries. Calling
--                   this DEGRADED implies a fault that does not exist, and
--                   AHR-SOURCE-900 §8 requires it to be reported separately so
--                   it never inflates the fulltext success rate.
--
--   RATE_LIMITED  - the provider's quota is exhausted. This says nothing about
--                   source health; treating it as QUARANTINED permanently
--                   sidelines a working source.

ALTER TABLE source DROP CONSTRAINT IF EXISTS ck_source_state;

ALTER TABLE source ADD CONSTRAINT ck_source_state CHECK (
    runtime_state IN (
        'CONFIGURED',
        'PROBING',
        'ACTIVE',
        'METADATA_ONLY',
        'RATE_LIMITED',
        'DEGRADED',
        'QUARANTINED',
        'DISABLED'
    )
);

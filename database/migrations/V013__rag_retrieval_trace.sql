-- Per-candidate retrieval trace (T1-1).
--
-- `rag_query.metrics` already records what happened in aggregate — how many
-- candidates each channel returned, how long each stage took, how many
-- passages story folding removed. What it cannot answer is the question
-- anyone debugging a wrong answer actually asks: *why this passage and not
-- that one*.
--
-- Every number needed to answer that is computed during a query and then
-- discarded. `FusedHit` even carries which channels found a chunk and which
-- §6 adjustments were applied to it; nothing reads those fields after fusion.
-- This table is the read path for work that is already being done.
--
-- Bounded on purpose: only the candidates that entered the rerank window are
-- kept (plus anything that survived into the evidence set), because a passage
-- ranked 300th by fusion was never in contention and storing it would grow the
-- table by an order of magnitude to record a non-decision.

CREATE TABLE rag_trace (
    rag_query_id      UUID NOT NULL REFERENCES rag_query(id) ON DELETE CASCADE,
    content_chunk_id  UUID NOT NULL,
    content_item_id   UUID,

    -- Where each channel put it. NULL means that channel never returned it,
    -- which is itself the interesting signal: a passage found only by the
    -- keyword channel is the MXFP4 case that motivated hybrid retrieval.
    dense_rank        INT,
    dense_score       DOUBLE PRECISION,
    sparse_rank       INT,
    sparse_score      DOUBLE PRECISION,

    -- Provenance already carried by FusedHit and never persisted until now.
    channels          VARCHAR(40),
    boosts            TEXT,

    fused_rank        INT,
    fused_score       DOUBLE PRECISION,

    -- NULL when the candidate fell outside the 40-candidate rerank window that
    -- B4 measured as better than 100 on every metric.
    rerank_rank       INT,
    rerank_score      DOUBLE PRECISION,

    final_rank        INT,

    -- Why it ended where it did. The elimination reasons are the point: a
    -- passage removed by the per-document cap and one removed by story folding
    -- look identical in the answer and mean completely different things.
    outcome           VARCHAR(32) NOT NULL,

    PRIMARY KEY (rag_query_id, content_chunk_id)
);

COMMENT ON COLUMN rag_trace.outcome IS
    'cited | evidence_uncited | dropped_document_cap | dropped_story_fold '
    '| dropped_budget | ranked_out';

-- The trace is always read for one query, ordered by how far the candidate got.
CREATE INDEX idx_rag_trace_query ON rag_trace (rag_query_id, fused_rank);

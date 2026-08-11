"""What happened to every candidate, recorded as it happens (T1-1).

The pipeline already computes everything needed to explain a ranking and then
throws it away at each hand-off: channel ranks vanish into RRF, `FusedHit`
carries `channels` and `boosts` that nothing reads afterwards, and the reasons
`select_evidence` drops a passage — the per-document cap, story folding, the
budget — are not distinguishable from the outside once the answer is rendered.

So a reader looking at an answer can see *which* passages were used and has no
way to ask why those. That is the question anyone debugging a wrong answer
starts with, and until now the only way to get at it was to add print
statements and re-run.

This module is an observer. It records; it never decides. Nothing downstream
reads a `RetrievalTrace`, so a bug in here can make the explanation wrong but
cannot make the answer wrong — which is the right way round for a component
whose entire purpose is to be believed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Only candidates that entered the rerank window are kept. B4 fixed that window
# at 40, and a passage fusion ranked 300th was never in contention — storing it
# would multiply the table to record a non-decision.
TRACE_LIMIT = 40

# Outcomes, most-selected first. The two "dropped" reasons are deliberately
# separate: one means a single document tried to fill the evidence set with its
# own paragraphs, the other means several outlets covered one event. They look
# the same in the answer and mean entirely different things.
CITED = "cited"
EVIDENCE_UNCITED = "evidence_uncited"
DROPPED_DOCUMENT_CAP = "dropped_document_cap"
DROPPED_SOURCE_CAP = "dropped_source_cap"
DROPPED_STORY_FOLD = "dropped_story_fold"
DROPPED_BUDGET = "dropped_budget"
RANKED_OUT = "ranked_out"


@dataclass
class Candidate:
    chunk_id: str
    content_item_id: str = ""
    dense_rank: int | None = None
    dense_score: float | None = None
    sparse_rank: int | None = None
    sparse_score: float | None = None
    channels: str = ""
    boosts: str = ""
    fused_rank: int | None = None
    fused_score: float | None = None
    rerank_rank: int | None = None
    rerank_score: float | None = None
    final_rank: int | None = None
    outcome: str = RANKED_OUT


@dataclass
class RetrievalTrace:
    """Accumulates one row per candidate as the query moves through the stages."""

    candidates: dict[str, Candidate] = field(default_factory=dict)

    def _for(self, chunk_id: str, content_item_id: str = "") -> Candidate:
        candidate = self.candidates.get(chunk_id)
        if candidate is None:
            candidate = Candidate(chunk_id=chunk_id, content_item_id=content_item_id)
            self.candidates[chunk_id] = candidate
        elif content_item_id and not candidate.content_item_id:
            candidate.content_item_id = content_item_id
        return candidate

    def record_channel(self, name: str, hits: list[Any]) -> None:
        """Rank and score as one channel saw it, before any fusion."""
        for rank, hit in enumerate(hits, start=1):
            candidate = self._for(hit.chunk_id, hit.content_item_id)
            if name == "dense":
                candidate.dense_rank, candidate.dense_score = rank, float(hit.score)
            elif name == "sparse":
                candidate.sparse_rank, candidate.sparse_score = rank, float(hit.score)

    def record_fusion(self, fused: list[Any]) -> None:
        for rank, hit in enumerate(fused, start=1):
            candidate = self._for(hit.chunk_id, hit.content_item_id)
            candidate.fused_rank = rank
            candidate.fused_score = float(hit.score)
            candidate.channels = "+".join(getattr(hit, "channels", ()) or ())
            candidate.boosts = ",".join(getattr(hit, "boosts", ()) or ())

    def record_rerank(self, hits: list[Any]) -> None:
        """After the cross-encoder *and* the §6 post-processing that follows it.

        One rank, not two: `directness`, `source_fit` and `temporal_fit` are
        adjustments to the cross-encoder's output rather than a separate stage,
        and B7/B9 measured them in exactly that position.
        """
        for rank, hit in enumerate(hits, start=1):
            candidate = self._for(hit.chunk_id, hit.content_item_id)
            candidate.rerank_rank = rank
            candidate.rerank_score = float(hit.score)

    def record_final(self, hits: list[Any]) -> None:
        for rank, hit in enumerate(hits, start=1):
            self._for(hit.chunk_id, hit.content_item_id).final_rank = rank

    def record_outcomes(self, outcomes: dict[str, str]) -> None:
        for chunk_id, outcome in outcomes.items():
            self._for(chunk_id).outcome = outcome

    def mark_cited(self, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            candidate = self.candidates.get(chunk_id)
            if candidate is not None:
                candidate.outcome = CITED

    #: Outcomes that mean the candidate reached the evidence set.
    SURVIVED = (CITED, EVIDENCE_UNCITED)

    def rows(self, limit: int = TRACE_LIMIT) -> list[Candidate]:
        """The candidates worth storing: the rerank window, plus every survivor.

        A passage that reached the evidence set is always kept even if fusion
        ranked it badly — that combination is the interesting one, and cutting
        it would hide the cases where the reranker rescued something.

        "Survivor" means it reached the evidence set, not merely that some rule
        put a label on it. `select_evidence` walks the whole ranking and labels
        almost everything, so treating any label as a reason to keep the row
        made the bound meaningless: a real query stored 64 rows under a limit
        of 40.
        """
        ordered = sorted(
            self.candidates.values(),
            key=lambda c: c.fused_rank if c.fused_rank is not None else 10**6,
        )
        kept = ordered[:limit]
        keys = {c.chunk_id for c in kept}
        kept.extend(
            c for c in ordered[limit:] if c.outcome in self.SURVIVED and c.chunk_id not in keys
        )
        return kept


def persist(connection: Any, query_id: Any, trace: RetrievalTrace) -> int:
    """Write the trace alongside the query it explains."""
    rows = trace.rows()
    if not rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO rag_trace (
                rag_query_id, content_chunk_id, content_item_id,
                dense_rank, dense_score, sparse_rank, sparse_score,
                channels, boosts, fused_rank, fused_score,
                rerank_rank, rerank_score, final_rank, outcome
            ) VALUES (
                %s, %s::uuid, NULLIF(%s, '')::uuid,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (rag_query_id, content_chunk_id) DO NOTHING
            """,
            [
                (
                    query_id,
                    row.chunk_id,
                    row.content_item_id,
                    row.dense_rank,
                    row.dense_score,
                    row.sparse_rank,
                    row.sparse_score,
                    row.channels,
                    row.boosts,
                    row.fused_rank,
                    row.fused_score,
                    row.rerank_rank,
                    row.rerank_score,
                    row.final_rank,
                    row.outcome,
                )
                for row in rows
            ],
        )
    return len(rows)


def load(connection: Any, query_id: str) -> list[dict[str, Any]]:
    """Read a trace back, joined to enough context to be readable.

    Ordered by how far the candidate got rather than by any single score: the
    reader is following a narrowing funnel, so the passage that survived belongs
    at the top even when fusion disagreed.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.content_chunk_id::text, t.content_item_id::text,
                   COALESCE(ci.zh_title, ci.title), s.name, s.source_tier,
                   t.dense_rank, t.dense_score, t.sparse_rank, t.sparse_score,
                   t.channels, t.boosts, t.fused_rank, t.fused_score,
                   t.rerank_rank, t.rerank_score, t.final_rank, t.outcome,
                   left(ch.body_text, 160)
              FROM rag_trace t
              LEFT JOIN content_chunk ch ON ch.id = t.content_chunk_id
              LEFT JOIN content_revision cr ON cr.id = ch.content_revision_id
              LEFT JOIN content_item ci ON ci.id = cr.content_item_id
              LEFT JOIN source s ON s.id = ci.source_id
             WHERE t.rag_query_id = %s::uuid
             ORDER BY t.final_rank NULLS LAST, t.rerank_rank NULLS LAST, t.fused_rank
            """,
            (query_id,),
        )
        rows = cursor.fetchall()

    return [
        {
            "chunkId": row[0],
            "itemId": row[1],
            "title": row[2] or "",
            "sourceName": row[3] or "",
            "sourceTier": row[4] or "",
            "denseRank": row[5],
            "denseScore": row[6],
            "sparseRank": row[7],
            "sparseScore": row[8],
            "channels": row[9] or "",
            "boosts": [b for b in (row[10] or "").split(",") if b],
            "fusedRank": row[11],
            "fusedScore": row[12],
            "rerankRank": row[13],
            "rerankScore": row[14],
            "finalRank": row[15],
            "outcome": row[16],
            "excerpt": row[17] or "",
        }
        for row in rows
    ]

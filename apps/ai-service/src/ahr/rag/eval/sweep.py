"""Fusion weight tuning against the golden set.

`AHR-RAG-400` §5 requires the fusion weights to be tuned on the evaluation set
rather than shipped as constants, and `fusion.py` has carried a comment saying
exactly that since B3. This is the sweep that discharges it.

Two measurements made it affordable and pointed at the right target.

**Affordable**: the latency run put dense + sparse + fuse at 67ms combined,
under 1% of a query, while embedding costs 1853ms. So the channel outputs are
captured once per question and every weight combination is scored over the
cached lists. Re-running retrieval per configuration would have meant an
embedding round-trip per configuration for results that cannot differ — the
channels do not depend on the weights.

**The right target**: B4 showed the reranker is what orders the final list, and
that candidates past rank 40 almost never contain an answer. The reranker only
reorders; it cannot introduce a document fusion failed to surface. So fusion's
entire measurable contribution is *how much of the answer set reaches the
reranker*, which is Recall@40 — not MRR, which measures an ordering the
reranker is about to discard. Tuning fusion on MRR would tune it for someone
else's job.

Recall@10/20 and MRR are still reported, for continuity with B1–B7 and because
a configuration that wins on Recall@40 while collapsing the others would be
worth knowing about.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ahr.rag.embeddings import EmbeddingClient
from ahr.rag.eval.golden import GoldenSet
from ahr.rag.eval.metrics import dedupe_to_items, recall_at_k, reciprocal_rank
from ahr.rag.eval.runner import snapshot_window
from ahr.rag.fusion import apply_boosts, reciprocal_rank_fusion
from ahr.rag.planner import plan
from ahr.rag.retrieval import (
    KEYWORD_FTS_TOP_K,
    TEMPORAL_SQL_TOP_K,
    VECTOR_PASSAGE_TOP_K,
    ChunkHit,
    dense_search,
    load_item_metadata,
    sparse_search,
    temporal_search,
)

# The depth that decides. B4 fixed the rerank candidate set at 40, so a relevant
# item ranked 41st by fusion is invisible to everything downstream.
DECISION_DEPTH = 40
REPORT_DEPTHS = (10, 20, DECISION_DEPTH)

# Dense is pinned at 1.0 and only the other two move. RRF scores are linear in
# the weights — multiplying all of them by any constant scales every score
# equally and leaves the order untouched — so only the ratios are real. Sweeping
# all three would spend most of the grid re-measuring configurations that are
# arithmetically identical to ones already seen.
SPARSE_GRID = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2)
TEMPORAL_GRID = (0.0, 0.05, 0.1, 0.15, 0.25, 0.4)


@dataclass
class Capture:
    """One question's channel outputs, before any fusion."""

    question_id: str
    category: str
    answerable: bool
    relevant_ids: frozenset[str]
    channels: dict[str, list[ChunkHit]] = field(default_factory=dict)
    metadata: dict[str, dict[str, object]] = field(default_factory=dict)
    query_type: str = "explainer"
    window: tuple[datetime, datetime] | None = None


async def capture_channels(
    golden: GoldenSet,
    connection: Any,
    embedder: EmbeddingClient,
    *,
    dense_depth: int = VECTOR_PASSAGE_TOP_K,
    sparse_depth: int = KEYWORD_FTS_TOP_K,
    temporal_depth: int = TEMPORAL_SQL_TOP_K,
) -> list[Capture]:
    """Run each channel once per question and keep the raw ranked lists.

    Everything the weights influence happens after this point, so this is the
    only part of the sweep that costs an API call or a query.
    """
    captures: list[Capture] = []

    for question in golden.questions:
        retrieval_plan = plan(question.question, asked_at=question.asked_at)
        vectors = await embedder.embed([question.question])

        window = None
        if retrieval_plan.time_range is not None:
            window = (retrieval_plan.time_range.start, retrieval_plan.time_range.end)

        filter_window = snapshot_window(
            question.asked_at, window if retrieval_plan.freshness_required else None
        )

        channels: dict[str, list[ChunkHit]] = {
            "dense": dense_search(connection, vectors[0], limit=dense_depth, window=filter_window),
            "sparse": sparse_search(
                connection, question.question, limit=sparse_depth, window=filter_window
            ),
        }
        if window is not None:
            channels["temporal"] = temporal_search(
                connection,
                window=snapshot_window(question.asked_at, window),
                limit=temporal_depth,
            )

        item_ids = sorted({hit.content_item_id for hits in channels.values() for hit in hits})
        captures.append(
            Capture(
                question_id=question.id,
                category=question.category,
                answerable=question.answerable,
                relevant_ids=frozenset(question.relevant_ids),
                channels=channels,
                metadata=load_item_metadata(connection, item_ids),
                query_type=retrieval_plan.query_type,
                window=window,
            )
        )

    return captures


def score_weights(
    captures: list[Capture],
    weights: dict[str, float],
    *,
    use_boosts: bool = True,
) -> dict[str, Any]:
    """Fuse every captured question under one weight set and score it.

    Pure local computation — no query, no API call.
    """
    per_question: list[dict[str, Any]] = []

    for capture in captures:
        # Copy: `apply_boosts` rewrites scores in place, and the captures are
        # reused across every configuration in the grid.
        fused = reciprocal_rank_fusion(
            {name: list(hits) for name, hits in capture.channels.items()},
            weights=weights,
        )
        if use_boosts:
            fused = apply_boosts(
                fused,
                capture.metadata,
                query_type=capture.query_type,
                window=capture.window,
            )

        if not capture.answerable:
            continue

        ranked = dedupe_to_items([(hit.content_item_id, hit.score) for hit in fused])
        per_question.append(
            {
                "question_id": capture.question_id,
                "category": capture.category,
                **{
                    f"recall@{d}": recall_at_k(ranked, capture.relevant_ids, d)
                    for d in REPORT_DEPTHS
                },
                "mrr": reciprocal_rank(ranked, capture.relevant_ids),
            }
        )

    if not per_question:
        return {"scored": 0}

    summary: dict[str, Any] = {
        "weights": dict(weights),
        "scored": len(per_question),
        **{
            f"recall@{d}": round(statistics.fmean(r[f"recall@{d}"] for r in per_question), 4)
            for d in REPORT_DEPTHS
        },
        "mrr": round(statistics.fmean(r["mrr"] for r in per_question), 4),
    }

    by_category: dict[str, Any] = {}
    for category in sorted({r["category"] for r in per_question}):
        rows = [r for r in per_question if r["category"] == category]
        by_category[category] = {
            f"recall@{DECISION_DEPTH}": round(
                statistics.fmean(r[f"recall@{DECISION_DEPTH}"] for r in rows), 4
            ),
            "mrr": round(statistics.fmean(r["mrr"] for r in rows), 4),
        }
    summary["by_category"] = by_category
    return summary


def sweep(
    captures: list[Capture],
    *,
    sparse_grid: tuple[float, ...] = SPARSE_GRID,
    temporal_grid: tuple[float, ...] = TEMPORAL_GRID,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Score the full grid and rank the configurations."""
    results = [
        score_weights(captures, {"dense": 1.0, "sparse": sparse, "temporal": temporal})
        for sparse in sparse_grid
        for temporal in temporal_grid
    ]
    results = [r for r in results if r.get("scored")]

    # Ties on the decision metric broken by MRR: if two configurations deliver
    # the same candidate set to the reranker, prefer the one that already had it
    # in a better order — the reranker fails softer from a good starting point.
    ranked = sorted(
        results,
        key=lambda r: (-r[f"recall@{DECISION_DEPTH}"], -r["mrr"]),
    )

    return {
        "run_id": run_id or datetime.now(UTC).strftime("SWEEP-%Y%m%dT%H%M%SZ"),
        "config": {
            "variant": "fusion-weight-sweep",
            "decision_metric": f"recall@{DECISION_DEPTH}",
            "sparse_grid": list(sparse_grid),
            "temporal_grid": list(temporal_grid),
            "combinations": len(results),
            "questions": len(captures),
        },
        "best": ranked[0] if ranked else None,
        "results": ranked,
    }

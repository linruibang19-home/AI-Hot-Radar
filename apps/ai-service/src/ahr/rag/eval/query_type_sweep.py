"""Which `query_type` actually retrieves best, per question.

B16 measured the LLM planner at 0.9067 against the golden set's `category` while
retrieval got slightly *worse*. Two explanations were possible: the gain does not
transfer, or the yardstick is wrong. This decides between them.

`category` records what kind of question a human thinks it is. A planner needs
the plan that retrieves best, and `source_fit` shows how those come apart —
`explainer` is the only row with a negative entry (primary −0.3), so relabelling
a question from explainer to fact_check swings first-hand sources from a penalty
to +1.0. The label gets more "correct" and the ranking can get worse.

So this forces each of the six types on every question and reads the recall. The
result is a label defined by the thing the planner exists to serve, and it is
what `expected_query_type` should hold — if the two disagree with `category`
often, the gate has been measuring the wrong thing all along.

**Two retrievals per question, not six.** `query_type` reaches retrieval through
exactly three paths, and only one of them changes what comes back:

* `freshness_required` decides whether the time window filters the channels —
  true for `recent_updates` and `timeline`, false for the rest, so there are two
  distinct candidate sets, not six;
* `source_fit` reorders the reranked list — local, free;
* `temporal_fit` blends recency in — local, free, and gated on the same flag.

Following `sweep.py`, which established the pattern: fetch what the providers
must produce once, then score every configuration against the cache. Six full
passes would pay a rerank for candidate sets already in memory.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ahr.rag.dimensions import Candidate, apply_dimensions
from ahr.rag.embeddings import EmbeddingClient
from ahr.rag.eval.golden import GoldenQuestion, GoldenSet
from ahr.rag.eval.metrics import dedupe_to_items, recall_at_k
from ahr.rag.eval.runner import snapshot_window
from ahr.rag.fusion import apply_boosts, reciprocal_rank_fusion
from ahr.rag.planner import QUERY_TYPES, plan
from ahr.rag.rerank import DEFAULT_TOP_N, RerankClient
from ahr.rag.retrieval import (
    KEYWORD_FTS_TOP_K,
    VECTOR_PASSAGE_TOP_K,
    ChunkHit,
    dense_search,
    entity_names,
    expand_vendor_aliases,
    load_chunk_texts,
    load_item_metadata,
    resolve_query_entities,
    sparse_search,
)
from ahr.rag.temporal import Scored, apply_temporal_fit

FRESHNESS_TYPES = {"recent_updates", "timeline"}


@dataclass
class TypeScore:
    query_type: str
    recall_at_10: float
    recall_at_20: float


async def _candidates(
    connection: Any,
    client: EmbeddingClient,
    reranker: RerankClient,
    question: str,
    asked_at: datetime,
    *,
    windowed: bool,
) -> list[ChunkHit]:
    """One reranked candidate set, with or without the time filter applied."""
    retrieval_plan = plan(question, asked_at=asked_at)
    window = None
    if retrieval_plan.time_range is not None:
        window = (retrieval_plan.time_range.start, retrieval_plan.time_range.end)

    filter_window = snapshot_window(asked_at, window if windowed else None)
    vectors = await client.embed([question])

    ids = resolve_query_entities(connection, question)
    aliases = expand_vendor_aliases(connection, ids)
    names = entity_names(connection, ids)

    channels = {
        "dense": dense_search(
            connection, vectors[0], limit=VECTOR_PASSAGE_TOP_K, window=filter_window
        ),
        "sparse": sparse_search(
            connection,
            question,
            limit=KEYWORD_FTS_TOP_K,
            window=filter_window,
            extra_terms=aliases,
            entity_terms=names + aliases,
        ),
    }
    fused = reciprocal_rank_fusion(channels)
    metadata = load_item_metadata(connection, sorted({h.content_item_id for h in fused}))
    # Boosts need a query_type for the opinion-for-fact penalty. Neutral here:
    # a type is chosen below, and baking one in would decide the answer.
    fused = apply_boosts(fused, metadata, query_type="explainer", window=window, query_entities=ids)

    hits = [
        ChunkHit(
            chunk_id=h.chunk_id,
            content_item_id=h.content_item_id,
            score=h.score,
            title=h.title,
            source_name=h.source_name,
        )
        for h in fused
    ]
    if not hits:
        return []

    head = hits[:40]
    texts = load_chunk_texts(connection, [h.chunk_id for h in head])
    scored = await reranker.rerank(
        question, [texts.get(h.chunk_id, h.title) for h in head], top_n=DEFAULT_TOP_N
    )
    reordered = [
        ChunkHit(
            chunk_id=head[i].chunk_id,
            content_item_id=head[i].content_item_id,
            score=score,
            title=head[i].title,
            source_name=head[i].source_name,
        )
        for i, score in scored
    ]
    taken = {h.chunk_id for h in reordered}
    return reordered + [h for h in hits if h.chunk_id not in taken]


def _apply_type(
    connection: Any,
    hits: list[ChunkHit],
    question: str,
    asked_at: datetime,
    query_type: str,
) -> list[ChunkHit]:
    """The post-rerank reordering this type would produce. Local and free."""
    if not hits:
        return hits

    metadata = load_item_metadata(connection, sorted({h.content_item_id for h in hits}))
    ordered = apply_dimensions(
        [
            Candidate(
                key=h.chunk_id,
                relevance=h.score,
                title=h.title,
                source_tier=(
                    str(tier)
                    if (tier := metadata.get(h.content_item_id, {}).get("source_tier"))
                    else None
                ),
            )
            for h in hits
        ],
        question=question,
        query_type=query_type,
    )
    by_id = {h.chunk_id: h for h in hits}
    hits = [by_id[k] for k in ordered if k in by_id]

    if query_type in FRESHNESS_TYPES:
        retrieval_plan = plan(question, asked_at=asked_at)
        window = (
            (retrieval_plan.time_range.start, retrieval_plan.time_range.end)
            if retrieval_plan.time_range
            else None
        )
        metadata = load_item_metadata(connection, sorted({h.content_item_id for h in hits}))
        order = apply_temporal_fit(
            [
                Scored(
                    key=h.chunk_id,
                    relevance=h.score,
                    published_at=metadata.get(h.content_item_id, {}).get("published_at"),
                )
                for h in hits
            ],
            window=window,
            freshness_required=True,
        )
        by_id = {h.chunk_id: h for h in hits}
        hits = [by_id[k] for k in order if k in by_id]

    return hits


async def score_question(
    connection: Any,
    client: EmbeddingClient,
    reranker: RerankClient,
    question: GoldenQuestion,
) -> list[TypeScore]:
    """Recall for each of the six types, on one question."""
    sets = {
        windowed: await _candidates(
            connection, client, reranker, question.question, question.asked_at, windowed=windowed
        )
        for windowed in (True, False)
    }

    scores: list[TypeScore] = []
    relevant = question.relevant_ids
    for query_type in QUERY_TYPES:
        hits = _apply_type(
            connection,
            sets[query_type in FRESHNESS_TYPES],
            question.question,
            question.asked_at,
            query_type,
        )
        ranked = dedupe_to_items([(h.content_item_id, h.score) for h in hits])
        scores.append(
            TypeScore(
                query_type=query_type,
                recall_at_10=recall_at_k(ranked, relevant, 10),
                recall_at_20=recall_at_k(ranked, relevant, 20),
            )
        )
    return scores


def best_type(scores: list[TypeScore]) -> str | None:
    """The type with the highest Recall@10, or None when nothing separates them.

    Ties are common and meaningful: for most questions the type changes nothing
    that matters, and declaring a winner by tie-break order would manufacture a
    label out of noise — then a planner would be scored on reproducing it.
    """
    if not scores:
        return None
    ranked = sorted(scores, key=lambda s: (-s.recall_at_10, -s.recall_at_20, s.query_type))
    if len(ranked) > 1 and (
        ranked[0].recall_at_10,
        ranked[0].recall_at_20,
    ) == (ranked[1].recall_at_10, ranked[1].recall_at_20):
        return None
    return ranked[0].query_type


async def run_sweep(
    golden: GoldenSet,
    *,
    connection: Any,
    client: EmbeddingClient,
    reranker: RerankClient,
) -> dict[str, Any]:
    """Per question: what each type scores, and whether one of them wins."""
    rows: list[dict[str, Any]] = []
    for question in golden.questions:
        if not question.answerable:
            continue
        scores = await score_question(connection, client, reranker, question)
        winner = best_type(scores)
        rows.append(
            {
                "question_id": question.id,
                "category": question.category,
                "best_query_type": winner,
                "planner_query_type": plan(
                    question.question, asked_at=question.asked_at
                ).query_type,
                "recall_at_10": {s.query_type: round(s.recall_at_10, 4) for s in scores},
                "spread": round(
                    max(s.recall_at_10 for s in scores) - min(s.recall_at_10 for s in scores), 4
                ),
            }
        )

    decided = [r for r in rows if r["best_query_type"] is not None]
    flat = [r for r in rows if r["spread"] == 0.0]
    return {
        "questions": len(rows),
        # The headline. If most questions have no separating type, the gate is
        # scoring a choice that does not change the outcome.
        "no_single_winner": len(rows) - len(decided),
        "identical_across_all_six": len(flat),
        "mean_spread": round(statistics.fmean(r["spread"] for r in rows), 4) if rows else None,
        "category_matches_best": (
            round(
                sum(1 for r in decided if r["category"] == r["best_query_type"]) / len(decided), 4
            )
            if decided
            else None
        ),
        "planner_matches_best": (
            round(
                sum(1 for r in decided if r["planner_query_type"] == r["best_query_type"])
                / len(decided),
                4,
            )
            if decided
            else None
        ),
        "rows": rows,
    }

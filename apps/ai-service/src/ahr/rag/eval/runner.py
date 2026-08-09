"""Run the golden set against a retrieval configuration and score it.

The output is deliberately more than a set of averages. A single mean hides the
thing worth knowing — which category is failing — and the per-question rows are
what make a regression diagnosable rather than merely detectable.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from ahr.rag.dimensions import Candidate, apply_dimensions
from ahr.rag.embeddings import EmbeddingClient
from ahr.rag.eval.golden import CATEGORIES, GoldenQuestion, GoldenSet
from ahr.rag.eval.metrics import dedupe_to_items, ndcg_at_k, recall_at_k, reciprocal_rank
from ahr.rag.fusion import apply_boosts, reciprocal_rank_fusion
from ahr.rag.llm_planner import plan_with_llm
from ahr.rag.planner import plan
from ahr.rag.rerank import (
    DEFAULT_CANDIDATE_LIMIT,
    DEFAULT_TOP_N,
    RerankClient,
    RerankUnavailableError,
)
from ahr.rag.retrieval import (
    KEYWORD_FTS_TOP_K,
    TEMPORAL_SQL_TOP_K,
    VECTOR_PASSAGE_TOP_K,
    ChunkHit,
    dense_search,
    entity_names,
    expand_vendor_aliases,
    interleave,
    load_chunk_texts,
    load_item_metadata,
    resolve_query_entities,
    sparse_search,
    temporal_search,
)
from ahr.rag.temporal import Scored, apply_temporal_fit

logger = logging.getLogger(__name__)

# Far enough back to precede any stored item, so a cutoff can always be
# expressed as a window without a special case for "no lower bound".
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def snapshot_window(
    asked_at: datetime,
    plan_window: tuple[datetime, datetime] | None,
) -> tuple[datetime, datetime]:
    """Restrict retrieval to the corpus as it stood when the question was asked.

    Ingestion never stops, so without this the annotations rot: a question
    annotated with four relevant documents acquires a fifth overnight, recall is
    computed against an answer key that is now incomplete, and every rerun
    drifts. AHR-RAG-400 §14 asks for cross-version comparison against a corpus
    snapshot; `asked_at` is that snapshot.

    An earlier attempt instead demanded that `asked_at` stay ahead of the newest
    item. That is unmaintainable — it fails again with the next hour's ingest —
    and it also throws away the only thing making a rerun reproducible.
    """
    if plan_window is None:
        return (EPOCH, asked_at)
    return (plan_window[0], min(plan_window[1], asked_at))


# A variant is just "question in, ranked chunks out". Keeping the scoring path
# identical across variants is the whole point: a difference between two runs
# then has exactly one cause, the retrieval change under test.
#
# `asked_at` is passed per question rather than per run because the golden set
# pins it per question: a time-sensitive question resolved against the wall
# clock would give a different answer tomorrow, and the evaluation would stop
# being reproducible.
Retriever = Callable[[str, datetime], Awaitable[list[ChunkHit]]]

# Metrics are reported at these depths, in items (not chunks).
RECALL_DEPTHS = (10, 20)
NDCG_DEPTH = 10


@dataclass
class QuestionResult:
    question_id: str
    category: str
    answerable: bool
    top_score: float
    retrieved_items: int
    recall: dict[int, float] = field(default_factory=dict)
    mrr: float | None = None
    ndcg: float | None = None
    first_hit_rank: int | None = None
    missed_items: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    run_id: str
    config: dict[str, Any]
    questions: list[QuestionResult]

    def _answerable(self) -> list[QuestionResult]:
        return [q for q in self.questions if q.answerable]

    def summary(self) -> dict[str, Any]:
        scored = self._answerable()
        if not scored:
            return {"questions": 0}

        overall: dict[str, Any] = {
            "questions": len(self.questions),
            "scored": len(scored),
            "unanswerable": len(self.questions) - len(scored),
        }
        for depth in RECALL_DEPTHS:
            overall[f"recall@{depth}"] = round(statistics.fmean(q.recall[depth] for q in scored), 4)
        overall["mrr"] = round(statistics.fmean(q.mrr or 0.0 for q in scored), 4)
        overall[f"ndcg@{NDCG_DEPTH}"] = round(statistics.fmean(q.ndcg or 0.0 for q in scored), 4)

        by_category: dict[str, Any] = {}
        for category in CATEGORIES:
            rows = [q for q in scored if q.category == category]
            if not rows:
                continue
            by_category[category] = {
                "questions": len(rows),
                **{
                    f"recall@{depth}": round(statistics.fmean(q.recall[depth] for q in rows), 4)
                    for depth in RECALL_DEPTHS
                },
                "mrr": round(statistics.fmean(q.mrr or 0.0 for q in rows), 4),
                f"ndcg@{NDCG_DEPTH}": round(statistics.fmean(q.ndcg or 0.0 for q in rows), 4),
            }

        return {
            "overall": overall,
            "by_category": by_category,
            "abstention_separation": self.abstention_separation(),
        }

    def abstention_separation(self) -> dict[str, Any]:
        """Top-1 similarity for answerable vs unanswerable questions.

        There is no refusal threshold yet, and inventing one before looking at
        the data would be backwards. What the baseline can produce is the raw
        material for calibrating one: if the two distributions overlap heavily,
        no similarity cut-off will separate them and refusal has to be decided
        further down the pipeline instead.
        """
        answerable = [q.top_score for q in self.questions if q.answerable]
        unanswerable = [q.top_score for q in self.questions if not q.answerable]
        if not answerable or not unanswerable:
            return {}

        return {
            "answerable": {
                "n": len(answerable),
                "mean": round(statistics.fmean(answerable), 4),
                "min": round(min(answerable), 4),
                "p10": round(sorted(answerable)[max(0, len(answerable) // 10 - 1)], 4),
            },
            "unanswerable": {
                "n": len(unanswerable),
                "mean": round(statistics.fmean(unanswerable), 4),
                "max": round(max(unanswerable), 4),
                "p90": round(
                    sorted(unanswerable)[min(len(unanswerable) - 1, 9 * len(unanswerable) // 10)],
                    4,
                ),
            },
            "overlap": round(
                max(0.0, max(unanswerable) - min(answerable)),
                4,
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config": self.config,
            "summary": self.summary(),
            "questions": [asdict(q) for q in self.questions],
        }


async def run_variant(
    golden: GoldenSet,
    retrieve: Retriever,
    *,
    variant: str,
    config: dict[str, Any],
    run_id: str | None = None,
) -> EvalReport:
    """Score one retrieval configuration over the whole golden set."""
    results: list[QuestionResult] = []

    for question in golden.questions:
        hits = await retrieve(question.question, question.asked_at)
        ranked = dedupe_to_items([(hit.content_item_id, hit.score) for hit in hits])
        results.append(_score(question, ranked, top_chunk_score=hits[0].score if hits else 0.0))

    prefix = variant.split("-", 1)[0].upper()
    return EvalReport(
        run_id=run_id or datetime.now(UTC).strftime(f"{prefix}-%Y%m%dT%H%M%SZ"),
        config={
            "variant": variant,
            "recall_depths": list(RECALL_DEPTHS),
            "ndcg_depth": NDCG_DEPTH,
            "golden_files": list(golden.source_files),
            "golden_questions": len(golden),
            **config,
        },
        questions=results,
    )


def dense_retriever(
    connection: Any,
    client: EmbeddingClient,
    *,
    chunk_depth: int = VECTOR_PASSAGE_TOP_K,
) -> Retriever:
    async def retrieve(question: str, asked_at: datetime) -> list[ChunkHit]:
        vectors = await client.embed([question])
        return dense_search(
            connection, vectors[0], limit=chunk_depth, window=snapshot_window(asked_at, None)
        )

    return retrieve


def sparse_retriever(
    connection: Any,
    *,
    chunk_depth: int = KEYWORD_FTS_TOP_K,
) -> Retriever:
    async def retrieve(question: str, asked_at: datetime) -> list[ChunkHit]:
        return sparse_search(
            connection, question, limit=chunk_depth, window=snapshot_window(asked_at, None)
        )

    return retrieve


def rrf_retriever(
    connection: Any,
    client: EmbeddingClient,
    *,
    dense_depth: int = VECTOR_PASSAGE_TOP_K,
    sparse_depth: int = KEYWORD_FTS_TOP_K,
    temporal_depth: int = TEMPORAL_SQL_TOP_K,
    use_temporal: bool = True,
    use_boosts: bool = True,
    weights: dict[str, float] | None = None,
    llm: Any | None = None,
) -> Retriever:
    """B3: weighted RRF over dense + sparse (+ temporal), then §6 boosts.

    The temporal channel only runs when the plan resolved a time window. Adding
    it unconditionally would drag an explainer question toward whatever happened
    to be published last week.
    """

    async def retrieve(question: str, asked_at: datetime) -> list[ChunkHit]:
        # The planner under test, when one is supplied. Measured at 0.9067
        # against the golden set's own categories versus the regex planner's
        # 0.6667 — but classification accuracy is not retrieval accuracy, and
        # B8 is the standing reminder that an upstream gain can vanish
        # downstream. This is the switch that answers whether it survives.
        if llm is not None:
            retrieval_plan, _from_model = await plan_with_llm(llm, question, asked_at=asked_at)
        else:
            retrieval_plan = plan(question, asked_at=asked_at)
        vectors = await client.embed([question])

        window = None
        if retrieval_plan.time_range is not None:
            window = (retrieval_plan.time_range.start, retrieval_plan.time_range.end)

        # The window filters the relevance channels rather than only feeding a
        # channel of its own. §4 makes time/entity filtering the *primary*
        # channel for `recent_updates`, and the first B3 run showed why an
        # unfiltered dense channel cannot be rescued by fusion: it returns
        # months-old articles that are semantically perfect, and no amount of
        # reweighting turns those into an answer about last week.
        filter_window = snapshot_window(
            asked_at, window if retrieval_plan.freshness_required else None
        )

        # Aliases before the keyword channel, exactly as `service.retrieve`
        # does. Omitting them here would measure a configuration no reader ever
        # gets — the same divergence B7 and the temporal channel were caught in,
        # and the reason this line is a copy rather than a simplification.
        query_entities = resolve_query_entities(connection, question)
        aliases = expand_vendor_aliases(connection, query_entities)
        names = entity_names(connection, query_entities)

        channels: dict[str, list[ChunkHit]] = {
            "dense": dense_search(connection, vectors[0], limit=dense_depth, window=filter_window),
            "sparse": sparse_search(
                connection,
                question,
                limit=sparse_depth,
                window=filter_window,
                extra_terms=aliases,
                entity_terms=names + aliases,
            ),
        }

        if window is not None and use_temporal:
            channels["temporal"] = temporal_search(
                connection, window=snapshot_window(asked_at, window), limit=temporal_depth
            )

        fused = reciprocal_rank_fusion(channels, weights=weights)
        if use_boosts:
            metadata = load_item_metadata(
                connection, sorted({hit.content_item_id for hit in fused})
            )
            fused = apply_boosts(
                fused,
                metadata,
                query_type=retrieval_plan.query_type,
                window=window,
                query_entities=query_entities,
            )

        return [
            ChunkHit(
                chunk_id=hit.chunk_id,
                content_item_id=hit.content_item_id,
                score=hit.score,
                title=hit.title,
                source_name=hit.source_name,
            )
            for hit in fused
        ]

    return retrieve


def rerank_retriever(
    connection: Any,
    client: EmbeddingClient,
    reranker: RerankClient,
    *,
    dense_depth: int = VECTOR_PASSAGE_TOP_K,
    sparse_depth: int = KEYWORD_FTS_TOP_K,
    temporal_depth: int = TEMPORAL_SQL_TOP_K,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    top_n: int = DEFAULT_TOP_N,
    use_temporal_fit: bool = False,
    use_dimensions: bool = False,
    weights: dict[str, float] | None = None,
    llm: Any | None = None,
) -> Retriever:
    """B4: B3's candidate set, reordered by a cross-encoder.

    The reranker only reorders — it never introduces a document. Anything it
    drops below `top_n` is appended in fused order rather than discarded, so
    Recall@20 stays comparable with B3. Otherwise a reranker that keeps 24 of
    100 would appear to destroy recall, and the comparison the gate depends on
    would be meaningless.
    """
    fuse = rrf_retriever(
        connection,
        client,
        dense_depth=dense_depth,
        sparse_depth=sparse_depth,
        temporal_depth=temporal_depth,
        weights=weights,
        llm=llm,
    )

    async def retrieve(question: str, asked_at: datetime) -> list[ChunkHit]:
        fused = await fuse(question, asked_at)
        candidates = fused[:candidate_limit]
        if not candidates:
            return fused

        texts = load_chunk_texts(connection, [hit.chunk_id for hit in candidates])
        documents = [texts.get(hit.chunk_id, hit.title) for hit in candidates]

        try:
            scored = await reranker.rerank(question, documents, top_n=top_n)
        except RerankUnavailableError as exc:
            # A degraded reranker must fall back to the fused order, not fail
            # the query. AHR-RAG-400 §5 requires degradation to be recorded
            # rather than silent, which is what this log line is for.
            logger.warning("rerank unavailable, falling back to fused order: %s", exc)
            return fused

        reordered = [
            ChunkHit(
                chunk_id=candidates[index].chunk_id,
                content_item_id=candidates[index].content_item_id,
                score=score,
                title=candidates[index].title,
                source_name=candidates[index].source_name,
            )
            for index, score in scored
        ]

        if use_dimensions:
            reordered = _apply_dimensions(connection, reordered, question, asked_at)

        if use_temporal_fit:
            reordered = _apply_temporal_fit(connection, reordered, question, asked_at)

        taken = {hit.chunk_id for hit in reordered}
        tail = [hit for hit in fused if hit.chunk_id not in taken]
        return reordered + tail

    return retrieve


def _apply_dimensions(
    connection: Any,
    hits: list[ChunkHit],
    question: str,
    asked_at: datetime,
) -> list[ChunkHit]:
    """B9: §6's `directness` and `source_fit`, applied after the cross-encoder.

    After rather than before, for the reason B8 established: the reranker
    rewrites the fused order, so a signal folded into fusion does not survive to
    the answer.
    """
    retrieval_plan = plan(question, asked_at=asked_at)
    metadata = load_item_metadata(connection, sorted({h.content_item_id for h in hits}))

    candidates = [
        Candidate(
            key=hit.chunk_id,
            relevance=hit.score,
            title=hit.title,
            source_tier=(
                str(tier)
                if (tier := metadata.get(hit.content_item_id, {}).get("source_tier"))
                else None
            ),
        )
        for hit in hits
    ]
    order = apply_dimensions(candidates, question=question, query_type=retrieval_plan.query_type)
    by_id = {hit.chunk_id: hit for hit in hits}
    return [by_id[key] for key in order if key in by_id]


def _apply_temporal_fit(
    connection: Any,
    hits: list[ChunkHit],
    question: str,
    asked_at: datetime,
) -> list[ChunkHit]:
    """B7: blend the cross-encoder score with recency, for time-scoped queries.

    B4 improved every category but `recent_updates`, whose MRR fell from 0.7333
    to 0.6484 — a cross-encoder has no way to know that this morning's release
    beats an equally relevant one from three weeks ago.
    """
    retrieval_plan = plan(question, asked_at=asked_at)
    window = (
        (retrieval_plan.time_range.start, retrieval_plan.time_range.end)
        if retrieval_plan.time_range
        else None
    )

    metadata = load_item_metadata(connection, sorted({h.content_item_id for h in hits}))
    scored = [
        Scored(
            key=hit.chunk_id,
            relevance=hit.score,
            published_at=metadata.get(hit.content_item_id, {}).get("published_at"),
        )
        for hit in hits
    ]
    order = apply_temporal_fit(
        scored, window=window, freshness_required=retrieval_plan.freshness_required
    )
    by_id = {hit.chunk_id: hit for hit in hits}
    return [by_id[key] for key in order if key in by_id]


def union_retriever(
    connection: Any,
    client: EmbeddingClient,
    *,
    dense_depth: int = VECTOR_PASSAGE_TOP_K,
    sparse_depth: int = KEYWORD_FTS_TOP_K,
) -> Retriever:
    """B2: both channels, merged by round-robin rather than by score.

    The two channels' scores are not comparable — cosine similarity against
    `ts_rank_cd`, which is not BM25 and carries no IDF — so merging by score
    would silently let one channel's scale decide everything. Interleaving is
    the honest placeholder until RRF (which reads ranks, not scores) lands.
    """

    async def retrieve(question: str, asked_at: datetime) -> list[ChunkHit]:
        vectors = await client.embed([question])
        snapshot = snapshot_window(asked_at, None)
        dense = dense_search(connection, vectors[0], limit=dense_depth, window=snapshot)
        sparse = sparse_search(connection, question, limit=sparse_depth, window=snapshot)
        return interleave(dense, sparse)

    return retrieve


def _score(
    question: GoldenQuestion,
    ranked: list[Any],
    *,
    top_chunk_score: float,
) -> QuestionResult:
    result = QuestionResult(
        question_id=question.id,
        category=question.category,
        answerable=question.answerable,
        top_score=round(top_chunk_score, 4),
        retrieved_items=len(ranked),
    )

    if not question.answerable:
        # Nothing is relevant, so recall/MRR/nDCG are undefined. The useful
        # signal from these questions is the top score, recorded above.
        return result

    relevant = question.relevant_ids
    grades = {item.item_id: item.grade for item in question.relevant_items}

    result.recall = {depth: recall_at_k(ranked, relevant, depth) for depth in RECALL_DEPTHS}
    result.mrr = reciprocal_rank(ranked, relevant)
    result.ndcg = ndcg_at_k(ranked, grades, NDCG_DEPTH)

    for position, entry in enumerate(ranked, start=1):
        if entry.item_id in relevant:
            result.first_hit_rank = position
            break

    found = {entry.item_id for entry in ranked}
    result.missed_items = sorted(relevant - found)
    return result

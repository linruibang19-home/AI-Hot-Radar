"""End-to-end question answering: plan → retrieve → rerank → generate → verify.

The retrieval configuration is the one the evaluation selected, not a fresh
guess: weighted RRF over dense + sparse with the time window used as a filter
(B3), reordered by the cross-encoder over 40 candidates (B4). Those choices have
numbers behind them — B4 measured MRR 0.8574 and nDCG@10 0.8162 against B1's
0.7630 / 0.7381 — and changing them here without re-running the golden set would
silently discard that evidence.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Json

from ahr import tracing
from ahr.config import get_settings
from ahr.processing.llm import LlmClient, LlmUnavailableError, TokenUsage
from ahr.rag.answer import (
    ANSWER_PROMPT_VERSION,
    MAX_EVIDENCE,
    MAX_PARENT_CHARS,
    SYSTEM_PROMPT,
    Answer,
    Citation,
    Evidence,
    bind_citations,
    build_user_prompt,
    check_invariants,
    drop_citations,
    load_evidence,
    parse_model_output,
    summarise_considered,
)
from ahr.rag.cache import (
    answer_key,
    corpus_fingerprint,
    get_answer,
    get_embedding,
    put_answer,
    put_embedding,
    record,
    semantic_lookup,
    semantic_remember,
)
from ahr.rag.cache import client as cache_client
from ahr.rag.dimensions import Candidate, apply_dimensions
from ahr.rag.embeddings import EmbeddingClient
from ahr.rag.folding import fold_by_story, load_chunk_facts, main_source_first
from ahr.rag.fusion import apply_boosts, reciprocal_rank_fusion
from ahr.rag.incremental import AnswerStream, JsonStringExtractor
from ahr.rag.parent import expand as expand_parent
from ahr.rag.planner import plan as build_plan
from ahr.rag.planner import plan_from_dict
from ahr.rag.rerank import DEFAULT_TOP_N, RerankClient, RerankUnavailableError
from ahr.rag.retrieval import (
    KEYWORD_FTS_TOP_K,
    VECTOR_PASSAGE_TOP_K,
    ChunkHit,
    dense_search,
    load_chunk_texts,
    load_item_metadata,
    resolve_query_entities,
    sparse_search,
)
from ahr.rag.router import DEFAULT_CANDIDATES
from ahr.rag.router import choose as choose_route
from ahr.rag.support import score_citations, summarise, unsupported_numbers
from ahr.rag.temporal import Scored, apply_temporal_fit
from ahr.rag.trace import (
    DROPPED_BUDGET,
    DROPPED_DOCUMENT_CAP,
    DROPPED_STORY_FOLD,
    EVIDENCE_UNCITED,
    RetrievalTrace,
)
from ahr.rag.trace import load as load_trace
from ahr.rag.trace import persist as persist_trace

logger = logging.getLogger(__name__)

# Kept as the default depth; the per-question choice lives in `router.py`.
RERANK_CANDIDATES = DEFAULT_CANDIDATES

# Called as each stage completes, so a caller can report progress while the
# query is still running. Optional: nothing in the pipeline depends on it, and
# the evaluation runs pass nothing.
StageReporter = Callable[[str, dict[str, Any]], Awaitable[None]]

# Called with each piece of the answer as it becomes safe to display. Also
# optional, and for the same reason: the evaluation harness wants the finished
# answer and nothing else.
DeltaReporter = Callable[[str], Awaitable[None]]


def add_stage_event(name: str, elapsed_ms: int, detail: dict[str, Any]) -> None:
    """Record one stage on the current span, if tracing is on."""
    if not tracing.enabled():
        return
    from opentelemetry import trace as otel

    current = otel.get_current_span()
    attributes = {
        f"ahr.{k}": v for k, v in detail.items() if isinstance(v, (str, int, float, bool))
    }
    current.add_event(f"stage.{name}", {**attributes, "ahr.ms": elapsed_ms})


async def _noop_stage(name: str, detail: dict[str, Any]) -> None:
    return None


async def _generate(
    llm: LlmClient,
    *,
    system_prompt: str,
    user_prompt: str,
    evidence: list[Evidence],
    on_delta: DeltaReporter | None,
) -> tuple[str, TokenUsage]:
    """Produce the model's raw response, streaming it out when someone is listening.

    Both paths return the same complete string, which is then parsed, bound and
    checked exactly as before. Streaming changes when the reader sees the answer,
    never what the server considers the answer to be — if the two could differ,
    the streamed copy would be an unverified second source of truth.
    """
    if on_delta is None:
        return await llm.summarize(system_prompt=system_prompt, user_prompt=user_prompt)

    usage = TokenUsage()
    extractor = JsonStringExtractor("answer_markdown")
    stream = AnswerStream(evidence)
    raw: list[str] = []

    async for piece in llm.stream_summarize(
        system_prompt=system_prompt, user_prompt=user_prompt, usage=usage
    ):
        raw.append(piece)
        prose = extractor.feed(piece)
        if not prose:
            continue
        visible = stream.feed(prose)
        if visible:
            await on_delta(visible)

    tail = stream.finish()
    if tail:
        await on_delta(tail)

    return "".join(raw), usage


async def retrieve(
    connection: Any,
    question: str,
    *,
    embedder: EmbeddingClient,
    reranker: RerankClient | None,
    asked_at: datetime,
    on_stage: StageReporter | None = None,
    trace: RetrievalTrace | None = None,
    query_vector: list[float] | None = None,
) -> tuple[list[ChunkHit], Any, dict[str, Any]]:
    """The B4 pipeline, returning hits, the frozen plan, and what happened.

    `trace` observes; it never decides. Every number it records is already
    computed here and discarded at the next hand-off — channel ranks disappear
    into RRF, and `FusedHit.channels` / `.boosts` are read by nothing.
    """
    started = time.monotonic()
    stages: dict[str, int] = {}
    report = on_stage or _noop_stage

    async def mark(name: str, since: float, **detail: Any) -> None:
        stages[name] = int((time.monotonic() - since) * 1000)
        # The stages already announce themselves for the progress stream, so
        # the span events hang off that rather than wrapping each stage
        # separately — nine call sites would drift, one does not.
        add_stage_event(name, stages[name], detail)
        await report(name, {"ms": stages[name], **detail})

    step = time.monotonic()
    retrieval_plan = build_plan(question, asked_at=asked_at)
    await mark(
        "plan",
        step,
        query_type=retrieval_plan.query_type,
        time_range=(retrieval_plan.time_range.label if retrieval_plan.time_range else None),
    )

    window = None
    if retrieval_plan.time_range is not None:
        window = (retrieval_plan.time_range.start, retrieval_plan.time_range.end)
    filter_window = window if retrieval_plan.freshness_required else None

    # The caller may have embedded the question already — it has to, if it
    # wants to consult the semantic cache, which needs the vector to look
    # anything up. Re-embedding here would pay for the same vector twice.
    step = time.monotonic()
    vector = query_vector if query_vector is not None else (await embedder.embed([question]))[0]
    await mark("embed", step, cached=query_vector is not None)

    step = time.monotonic()
    dense = dense_search(connection, vector, limit=VECTOR_PASSAGE_TOP_K, window=filter_window)
    await mark("dense", step, found=len(dense))

    step = time.monotonic()
    sparse = sparse_search(connection, question, limit=KEYWORD_FTS_TOP_K, window=filter_window)
    await mark("sparse", step, found=len(sparse))

    channels: dict[str, list[ChunkHit]] = {"dense": dense, "sparse": sparse}
    if trace is not None:
        for name, rows in channels.items():
            trace.record_channel(name, rows)

    step = time.monotonic()
    fused = reciprocal_rank_fusion(channels)
    metadata = load_item_metadata(connection, sorted({h.content_item_id for h in fused}))
    query_entities = resolve_query_entities(connection, question)
    fused = apply_boosts(
        fused,
        metadata,
        query_type=retrieval_plan.query_type,
        window=window,
        query_entities=query_entities,
    )
    await mark("fuse", step, found=len(fused), entities=len(query_entities))
    if trace is not None:
        trace.record_fusion(fused)

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

    # How deep the cross-encoder goes is a routing decision, measured per
    # question type rather than fixed (B12). See `router.py` for why the two
    # obvious "skip the reranker" rules were rejected by the golden set.
    route = choose_route(retrieval_plan.query_type)

    degraded: list[str] = []
    step = time.monotonic()
    if reranker is not None and hits:
        candidates = hits[: route.rerank_candidates]
        texts = load_chunk_texts(connection, [h.chunk_id for h in candidates])
        documents = [texts.get(h.chunk_id, h.title) for h in candidates]
        try:
            scored = await reranker.rerank(question, documents, top_n=DEFAULT_TOP_N)
            reordered = [
                ChunkHit(
                    chunk_id=candidates[i].chunk_id,
                    content_item_id=candidates[i].content_item_id,
                    score=score,
                    title=candidates[i].title,
                    source_name=candidates[i].source_name,
                )
                for i, score in scored
            ]
            # §6's other three dimensions, applied to the cross-encoder's
            # output and *before* the tail is appended — exactly the order B7
            # and B9 measured. Applying them to the merged list would also
            # reorder the candidates the reranker never scored, which is not
            # the configuration either evaluation ran.
            reordered = _rank_by_dimensions(
                connection, reordered, question, query_type=retrieval_plan.query_type
            )
            reordered = _rank_by_recency(
                connection,
                reordered,
                window=window,
                freshness_required=retrieval_plan.freshness_required,
            )

            if trace is not None:
                trace.record_rerank(reordered)

            taken = {h.chunk_id for h in reordered}
            hits = reordered + [h for h in hits if h.chunk_id not in taken]
        except RerankUnavailableError as exc:
            # §5 requires degradation to be recorded rather than silent. A dead
            # reranker costs ranking quality; it must not cost the answer.
            logger.warning("rerank unavailable, using fused order: %s", exc)
            degraded.append("rerank")
    elif reranker is None:
        degraded.append("rerank")
    await mark("rerank", step, degraded=bool(degraded), candidates=route.rerank_candidates)

    if trace is not None:
        trace.record_final(hits)

    metrics = {
        "route": route.as_metrics(),
        "channels": {name: len(rows) for name, rows in channels.items()},
        "fused": len(fused),
        "degraded": degraded,
        "retrieval_ms": int((time.monotonic() - started) * 1000),
        "stages_ms": stages,
    }
    return hits, retrieval_plan, metrics


def _rank_by_dimensions(
    connection: Any,
    hits: list[ChunkHit],
    question: str,
    *,
    query_type: str,
) -> list[ChunkHit]:
    """B9: §6's `directness` and `source_fit` over the reranked passages.

    Measured against B7 on the golden set: MRR 0.8645 -> 0.8731, `timeline`
    MRR +4.5pt, `explainer` Recall@10 +3.3pt, nothing worse than -0.0007.
    """
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
    order = apply_dimensions(candidates, question=question, query_type=query_type)
    by_id = {hit.chunk_id: hit for hit in hits}
    return [by_id[key] for key in order if key in by_id]


def _rank_by_recency(
    connection: Any,
    hits: list[ChunkHit],
    *,
    window: tuple[datetime, datetime] | None,
    freshness_required: bool,
) -> list[ChunkHit]:
    """B7: blend relevance with recency, for time-scoped questions only.

    A cross-encoder has no way to know that this morning's release beats an
    equally relevant one from three weeks ago. Measured at `recent_updates`
    MRR 0.6484 -> 0.7522, with the other five categories identical rank for
    rank — `freshness_required` keeps it entirely out of their way.
    """
    if not freshness_required:
        return hits

    metadata = load_item_metadata(connection, sorted({h.content_item_id for h in hits}))
    scored = [
        Scored(
            key=hit.chunk_id,
            relevance=hit.score,
            published_at=metadata.get(hit.content_item_id, {}).get("published_at"),
        )
        for hit in hits
    ]
    order = apply_temporal_fit(scored, window=window, freshness_required=True)
    by_id = {hit.chunk_id: hit for hit in hits}
    return [by_id[key] for key in order if key in by_id]


def select_evidence(
    connection: Any,
    hits: list[ChunkHit],
    *,
    per_item: int = 2,
    limit: int = MAX_EVIDENCE,
    trace: RetrievalTrace | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Turn a ranking into an evidence set: cap per document, then fold events.

    Two different redundancies, so two passes. The per-document cap stops one
    long release note filling every slot with its own paragraphs; story folding
    stops one *event* filling them with three outlets' coverage of it. Neither
    subsumes the other — the Anthropic incident was three separate documents.

    `trace` records *which* rule removed each passage. From the finished answer
    the two look identical, and they mean opposite things — one says a document
    was over-represented, the other says an event was.
    """
    capped: list[str] = []
    seen: dict[str, int] = {}
    outcomes: dict[str, str] = {}
    for hit in hits:
        count = seen.get(hit.content_item_id, 0)
        if count >= per_item:
            outcomes[hit.chunk_id] = DROPPED_DOCUMENT_CAP
            continue
        seen[hit.content_item_id] = count + 1
        capped.append(hit.chunk_id)
        # Fold from a wider pool than the budget: passages dropped as duplicate
        # coverage have to be replaced by the next distinct thing, not simply
        # leave the evidence set short.
        if len(capped) >= limit * 3:
            break

    facts = load_chunk_facts(connection, capped)
    fold_reasons: dict[str, str] = {}
    folded = fold_by_story(capped, facts, limit=limit, reasons=fold_reasons)
    ordered = main_source_first(folded, facts)

    if trace is not None:
        for chunk_id in folded:
            outcomes[chunk_id] = EVIDENCE_UNCITED
        for chunk_id, why in fold_reasons.items():
            outcomes[chunk_id] = DROPPED_BUDGET if why == "budget" else DROPPED_STORY_FOLD
        trace.record_outcomes(outcomes)

    stats = {
        "candidates": len(capped),
        "after_story_folding": len(folded),
        "stories_folded": len(capped) - len(folded),
    }
    return ordered, stats


@dataclass
class _CacheState:
    """What the cache lookup learned, carried into the uncached path.

    The vector especially: a semantic miss has still embedded the question, and
    discarding it would make every miss pay for the same vector twice.
    """

    key: str
    fingerprint: str
    vector: list[float] | None = None
    embedding_hit: bool = False

    def as_metrics(self) -> dict[str, Any]:
        return {
            "outcome": "miss",
            "embedding": "hit" if self.embedding_hit else "miss",
            "fingerprint": self.fingerprint[:8],
        }


def _replay(payload: dict[str, Any], *, outcome: str, similarity: float | None) -> Answer:
    """Rebuild an `Answer` from a cached payload.

    Citations are rehydrated into real `Citation` objects rather than passed
    through as dicts, so a cached answer serialises through exactly the same
    `as_dict` as a fresh one. A second serialisation path is how the cached copy
    would start to differ from the live one without anybody noticing.

    `queryId` is kept from the original: a cache hit *is* that answer, and its
    permalink already holds the trace and the citations that explain it.
    """
    citations = [
        Citation(
            number=int(row.get("number", index + 1)),
            chunk_id=str(row.get("chunkId", "")),
            content_item_id=str(row.get("itemId", "")),
            claim_text=str(row.get("claim") or ""),
            title=str(row.get("title") or ""),
            source_name=str(row.get("sourceName") or ""),
            canonical_url=str(row.get("url") or ""),
            published_at=None,
            source_tier=str(row.get("sourceTier") or "secondary"),
            story_slug=row.get("storySlug"),
            independent_sources=int(row.get("independentSources") or 1),
            support_score=row.get("supportScore"),
        )
        for index, row in enumerate(payload.get("citations") or [])
    ]

    answer = Answer(
        question=str(payload.get("question", "")),
        answer_markdown=str(payload.get("answerMarkdown", "")),
        citations=citations,
        limitations=[str(x) for x in payload.get("limitations") or []],
        refused=False,
        # Rehydrated, not dropped: without it the page loses the query type and
        # the resolved time window, which are exactly what shows a reader that
        # "最近" became a real interval.
        plan=plan_from_dict(payload.get("plan")),
        model=payload.get("model"),
        metrics={
            **(payload.get("metrics") or {}),
            "cache": {"outcome": outcome, "similarity": similarity},
        },
        considered=list(payload.get("considered") or []),
    )
    answer.query_id = payload.get("queryId")
    # The published dates are dropped on the way through JSON; the permalink
    # carries the authoritative copy, and a wrong date is worse than none.
    return answer


async def _from_cache(
    connection: Any,
    question: str,
    *,
    embedder: EmbeddingClient,
    asked_at: datetime,
    report: StageReporter,
    bypass: bool = False,
) -> tuple[Answer | None, _CacheState]:
    """Serve from cache when it is safe to, and report why when it is not.

    Two layers, in cost order. The exact key is checked before any provider is
    touched at all; the semantic near-match needs the question embedded, so it
    comes after that one call and still saves rerank and generation — 81% of a
    query by the latency run's measurement.

    Every failure path returns a miss. A cache that can break the feature is
    worse than no cache, so nothing here raises.
    """
    # The plan decides how tightly this answer is bound to the corpus. Built
    # here as well as in `retrieve`: it is a pure function of the question and
    # the clock, so both calls agree, and threading it through would put a
    # retrieval concern into the cache's signature for no gain.
    plan = build_plan(question, asked_at=asked_at)
    fingerprint = corpus_fingerprint(connection, freshness_required=plan.freshness_required)
    key = answer_key(question, fingerprint=fingerprint, prompt_version=ANSWER_PROMPT_VERSION)
    state = _CacheState(key=key, fingerprint=fingerprint)
    client = cache_client()

    step = time.monotonic()
    stored = None if bypass else await get_answer(client, key)
    if stored is not None:
        await record(client, "exact")
        await report("cache", {"ms": int((time.monotonic() - step) * 1000), "outcome": "exact"})
        return _replay(stored, outcome="exact", similarity=None), state

    # Layer 2 needs the vector, so the embedding happens here rather than inside
    # `retrieve`, and is handed onward so it is only paid for once.
    vector = await get_embedding(client, embedder.model_name, question)
    state.embedding_hit = vector is not None
    if vector is None:
        try:
            vector = (await embedder.embed([question]))[0]
        except Exception as exc:  # noqa: BLE001 - let `retrieve` raise it properly
            logger.warning("cache pre-embed failed, falling through: %s", exc)
            await record(client, "embed_miss")
            return None, state
        await put_embedding(client, embedder.model_name, question, vector)
        await record(client, "embed_miss")
    else:
        await record(client, "embed_hit")

    state.vector = vector

    near = None if bypass else await semantic_lookup(client, vector, fingerprint=fingerprint)
    if near is not None:
        neighbour, similarity = near
        stored = await get_answer(client, neighbour)
        if stored is not None:
            await record(client, "semantic")
            await report(
                "cache",
                {
                    "ms": int((time.monotonic() - step) * 1000),
                    "outcome": "semantic",
                    "similarity": round(similarity, 4),
                },
            )
            return _replay(stored, outcome="semantic", similarity=round(similarity, 4)), state

    await record(client, "miss")
    return None, state


async def _store_in_cache(answer: Answer, state: _CacheState) -> None:
    """Remember a fresh answer, and index its question for near-matching.

    Refusals are filtered inside `put_answer` rather than here, so every call
    site inherits the rule instead of having to remember it.
    """
    client = cache_client()
    await put_answer(client, state.key, answer.as_dict())
    if state.vector is not None and not answer.refused:
        await semantic_remember(client, state.vector, key=state.key, fingerprint=state.fingerprint)


async def answer_question(
    question: str,
    *,
    embedder: EmbeddingClient,
    reranker: RerankClient | None,
    llm: LlmClient,
    asked_at: datetime | None = None,
    persist: bool = True,
    on_stage: StageReporter | None = None,
    on_delta: DeltaReporter | None = None,
    bypass_cache: bool = False,
) -> Answer:
    """Answer one question, or refuse, and record what was cited.

    `on_delta`, when supplied, receives the answer as it is generated. What it
    receives is already resolved — invented citation numbers are gone and the
    real ones carry their final reading-order number — and nothing reaches it
    until the answer is guaranteed not to become a refusal. See
    `incremental.py`; the verified result still arrives in full at the end.
    """
    moment = asked_at or datetime.now(UTC)
    started = time.monotonic()
    report = on_stage or _noop_stage
    trace = RetrievalTrace()

    with (
        tracing.span("rag.answer", question_chars=len(question)),
        psycopg.connect(get_settings().database_url) as connection,
    ):
        # Two cache layers, consulted at the two points where they can save the
        # most: the exact key before anything external is called at all, and the
        # semantic near-match after embedding but before rerank and generation —
        # which together are 81% of a query (ADR-0017).
        cached, cache_state = await _from_cache(
            connection,
            question,
            embedder=embedder,
            asked_at=moment,
            report=report,
            bypass=bypass_cache,
        )
        if cached is not None:
            return cached

        hits, retrieval_plan, metrics = await retrieve(
            connection,
            question,
            embedder=embedder,
            reranker=reranker,
            asked_at=moment,
            on_stage=on_stage,
            trace=trace,
            query_vector=cache_state.vector,
        )
        metrics["cache"] = cache_state.as_metrics()
        step = time.monotonic()
        chunk_ids, selection_stats = select_evidence(connection, hits, trace=trace)
        metrics["selection"] = selection_stats
        evidence = load_evidence(connection, chunk_ids)
        metrics["stages_ms"]["select"] = int((time.monotonic() - step) * 1000)
        await report(
            "select",
            {
                "ms": metrics["stages_ms"]["select"],
                "evidence": len(evidence),
                "stories_folded": selection_stats.get("stories_folded", 0),
            },
        )

        # B5: each cited passage is generated from its parent block, while the
        # citation still points at the passage itself. The reader checks a
        # paragraph; the model reads enough of the document to be right about it.
        step = time.monotonic()
        tiers: dict[str, int] = {}
        for item in evidence:
            parent = expand_parent(connection, item.chunk_id)
            if parent is None:
                continue
            tiers[parent.tier] = tiers.get(parent.tier, 0) + 1
            item.text = parent.text[:MAX_PARENT_CHARS]
        metrics["parent_tiers"] = tiers
        metrics["stages_ms"]["parent"] = int((time.monotonic() - step) * 1000)
        await report("parent", {"ms": metrics["stages_ms"]["parent"], "tiers": tiers})

        if not evidence:
            result = Answer(
                question=question,
                answer_markdown="",
                citations=[],
                limitations=["检索没有返回任何内容"],
                refused=True,
                refusal_reason="检索为空",
                plan=retrieval_plan,
                metrics=metrics,
                asked_at=moment,
            )
            if persist:
                _persist(connection, result)
            return result

        step = time.monotonic()
        await report("generate", {"ms": 0, "started": True})
        try:
            raw, usage = await _generate(
                llm,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(question, evidence, retrieval_plan),
                evidence=evidence,
                on_delta=on_delta,
            )
        except LlmUnavailableError as exc:
            logger.warning("generation failed: %s", exc)
            return Answer(
                question=question,
                answer_markdown="",
                citations=[],
                limitations=[f"生成服务不可用：{exc}"],
                refused=True,
                refusal_reason="生成服务不可用",
                plan=retrieval_plan,
                metrics=metrics,
            )

        metrics["stages_ms"]["generate"] = int((time.monotonic() - step) * 1000)

        parsed = parse_model_output(raw)
        text, citations, dangling, limitations = bind_citations(
            str(parsed.get("answer_markdown") or ""),
            list(parsed.get("claims") or []),
            evidence,
            limitations=[str(x) for x in (parsed.get("limitations") or [])],
        )

        refused = not text or not citations
        refusal_reason = None
        if refused:
            # No grounded claim survived. Saying so is the required behaviour,
            # not a fallback: §10 forbids letting the model fill the gap from
            # general knowledge.
            refusal_reason = "检索到的内容不足以回答这个问题"

        # §10 layer ③, and the first version of it that decides anything.
        #
        # The score has been computed, stored and badged since T2-4 while
        # changing nothing: an answer could show a source the cross-encoder
        # scored 0.000 next to one it scored 0.998, both rendered identically as
        # "来源". Measured live, 11.11% of scored citations sit below the
        # threshold. `AHR-QSO-700` §8 asks for zero such defects, so the
        # citation is now removed rather than displayed.
        #
        # Removal only — this never escalates to a refusal. Dropping the last
        # citation would, via `check_invariants`, and the answers most exposed
        # to that are grounded denials, which score low for structural reasons
        # (29.41% weak against 10.22% for assertions). `unsupported_numbers`
        # keeps the strongest rather than empty the list.
        step = time.monotonic()
        scores = await score_citations(
            reranker,
            citations,
            {e.chunk_id: e.text for e in evidence},
            fallback_claim=question,
        )
        for citation in citations:
            citation.support_score = scores.get(citation.chunk_id)

        weak = unsupported_numbers(citations)
        if weak:
            text, citations, limitations = drop_citations(text, citations, limitations, drop=weak)
            limitations.append(
                f"有 {len(weak)} 条引用未通过支持度校验"
                "（交叉编码器判定证据不支持所配论断），已从答案中移除。"
            )
            metrics["support_dropped"] = len(weak)

        metrics["stages_ms"]["support"] = int((time.monotonic() - step) * 1000)
        metrics["support"] = summarise(scores, len(citations))
        await report("support", {"ms": metrics["stages_ms"]["support"], **metrics["support"]})

        violations = check_invariants(text, citations, evidence, refused=refused)
        if violations:
            logger.warning("answer failed invariants: %s", violations)
            refused = True
            refusal_reason = "回答未通过引用校验"
            text = ""
            citations = []
            limitations = [*limitations, *violations]

        if dangling:
            limitations.append(f"模型引用了不存在的证据编号：{', '.join(dangling)}")

        metrics.update(
            {
                "evidence": len(evidence),
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cached_tokens": usage.cached_tokens,
                "prompt_version": ANSWER_PROMPT_VERSION,
            }
        )

        # Into `llm_usage` as well, which is the table that answers "what has
        # the model cost". Answering was the one operation missing from it:
        # enrichment and recommendations were recorded from the start, while
        # the RAG path — the only one exposed to the public internet, and the
        # expensive one per call — reported its tokens solely into this query's
        # own metrics blob. Any spend report built from `llm_usage` was
        # therefore quietly excluding the thing most worth watching.
        _record_answer_usage(connection, model=llm.model_name, usage=usage, serving=persist)

        # Support scoring used to sit here, after the answer was already fixed.
        # It has moved above `check_invariants`, because a score that arrives
        # after the decision it should inform can only be decoration.

        # `total_ms` last, because support scoring is part of the request.
        #
        # It used to be stamped just after generation, which left the support
        # stage — a reranker round trip, median 2.3s — outside the total the
        # dashboard reports as end-to-end latency. Two consequences, and the
        # second is how it surfaced: p50 was understated by roughly that much,
        # and the stage shares summed to 122.7% because one of the stages was
        # being divided by a total that excluded it.
        #
        # The reader waits for support scoring like everything else, so it
        # counts. Recomputing the shares was treating the symptom.
        metrics["total_ms"] = int((time.monotonic() - started) * 1000)

        result = Answer(
            question=question,
            answer_markdown=text,
            citations=citations,
            limitations=limitations,
            refused=refused,
            refusal_reason=refusal_reason,
            plan=retrieval_plan,
            model=llm.model_name,
            metrics=metrics,
            considered=summarise_considered(evidence),
        )
        if persist:
            _persist(connection, result)
            # After `_persist`, which is what assigns the id the trace hangs
            # off. Failing to write the trace must not lose the answer: the
            # explanation is worth having, but not at the price of the thing it
            # explains.
            trace.mark_cited([c.chunk_id for c in citations])
            try:
                persist_trace(connection, uuid.UUID(str(result.query_id)), trace)
                connection.commit()
            except Exception as exc:  # noqa: BLE001 - see above
                connection.rollback()
                logger.warning("retrieval trace not stored: %s", exc)

            # Inside `persist`, not beside it. A cached answer carries the
            # `queryId` its permalink points at, so caching an answer that was
            # never recorded would hand out a link to nothing — and the
            # evaluation runs with `persist=False` precisely so it does not
            # leave 90 synthetic rows behind. It must not leave 90 cache
            # entries behind either.
            await _store_in_cache(result, cache_state)

        return result


HISTORY_LIMIT = 20


# One query serves both the history list and a single permalink. They must
# agree: a conversation that renders one way in the list and another way at its
# own URL is two features telling the reader different things about one answer.
_CONVERSATION_SELECT = """
    SELECT q.id::text, q.question, q.answer_markdown, q.status,
           q.retrieval_plan, q.metrics, q.completed_at, q.limitations,
           COALESCE(
               json_agg(
                   json_build_object(
                       'number', c.citation_no,
                       'claim', c.claim_text,
                       'itemId', ci.id::text,
                       'title', COALESCE(ci.zh_title, ci.title),
                       'sourceName', s.name,
                       'url', ci.canonical_url,
                       'publishedAt', COALESCE(ci.published_at, ci.observed_at),
                       'sourceTier', s.source_tier,
                       'storySlug', st.slug,
                       'independentSources', COALESCE(st.independent_source_count, 1),
                       'supportScore', c.support_score
                   )
                   ORDER BY c.citation_no
               ) FILTER (WHERE c.citation_no IS NOT NULL),
               '[]'
           )
      FROM rag_query q
      LEFT JOIN rag_citation c ON c.rag_query_id = q.id
      LEFT JOIN content_chunk ch ON ch.id = c.content_chunk_id
      LEFT JOIN content_revision cr ON cr.id = ch.content_revision_id
      LEFT JOIN content_item ci ON ci.id = cr.content_item_id
      LEFT JOIN source s ON s.id = ci.source_id
      LEFT JOIN story st ON st.id = ci.story_id
"""


def _as_conversation(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "queryId": row[0],
        "question": row[1],
        "answerMarkdown": row[2] or "",
        "refused": row[3] == "REFUSED",
        "refusalReason": "检索到的内容不足以回答这个问题" if row[3] == "REFUSED" else None,
        # V015. Before that column existed this was hard-coded to `[]`, so a
        # permalink showed the answer with its qualifications stripped off —
        # a more confident version of what was actually said.
        "limitations": row[7] or [],
        "plan": row[4] or {},
        "metrics": row[5] or {},
        "askedAt": row[6].isoformat() if row[6] else None,
        "citations": row[8] or [],
        # Not persisted: `considered` is a retrieval-time view, and storing
        # it would duplicate rows that already exist as content_item.
        "considered": [],
    }


def load_history(connection: Any, limit: int = HISTORY_LIMIT) -> list[dict[str, Any]]:
    """Recent conversations, newest first, in the shape the client already renders.

    Reconstructed from `rag_query` and `rag_citation` rather than from a second
    store: those rows are the record of what was said and what it was based on,
    written in the same transaction as the answer. Reading them back is the
    whole feature — the data has been accumulating since the first query.

    Deliberately global rather than per-user: there are no accounts until M5.
    That is a real limitation and is stated on the page, not hidden.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            _CONVERSATION_SELECT
            + """
             GROUP BY q.id
             ORDER BY q.completed_at DESC NULLS LAST
             LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    return [_as_conversation(row) for row in rows]


def load_conversation(connection: Any, query_id: str) -> dict[str, Any] | None:
    """One conversation by id, or None.

    This is what makes an answer addressable. Every answer has been written to
    `rag_query` since the feature shipped and the id has been returned to the
    client all along, but with no route that read it back the id pointed at
    nothing — an answer could be produced and never referred to again.
    """
    try:
        identifier = uuid.UUID(str(query_id))
    except (ValueError, AttributeError, TypeError):
        # A malformed id is a 404, not a 500: the path segment is user input.
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            _CONVERSATION_SELECT + " WHERE q.id = %s GROUP BY q.id",
            (identifier,),
        )
        row = cursor.fetchone()

    if row is None:
        return None

    conversation = _as_conversation(row)
    # Only the permalink carries the trace. The history list renders twenty
    # conversations and would pull forty candidate rows for each of them to
    # show something none of them displays.
    conversation["trace"] = load_trace(connection, str(query_id))
    return conversation


def _record_answer_usage(connection: Any, *, model: str, usage: TokenUsage, serving: bool) -> None:
    """Record one answer's provider-reported token usage (AHR-QSO-700 §5).

    `content_item_id` is null: an answer is about the corpus rather than about
    one item, and inventing an attribution would corrupt per-item cost figures.

    **Evaluation runs are recorded under a different operation.** They call the
    same generator with the same prompt and cost exactly as much, so they must
    be recorded — but they are not what the site cost to run, and folding them
    together makes the spend report unreadable in the direction that flatters
    it. Measured before this split: 416 `rag_answer` rows against 159 questions
    anyone actually asked, so **62% of the "RAG answer generation" line was
    evaluation** presented as production. Same family as the evaluation that was
    reading its own cache (§3.23 ①) — a measurement contaminated by the thing
    measuring it.

    `serving` follows `persist`: the only caller that does not persist is the
    evaluation harness, because its answers are not shown to anyone.
    """
    operation = "rag_answer" if serving else "rag_answer_eval"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO llm_usage (
                id, content_item_id, operation, model, prompt_version,
                prompt_tokens, completion_tokens, cached_tokens,
                attempts, succeeded, latency_ms
            ) VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            """,
            (
                uuid.uuid4(),
                operation,
                model,
                ANSWER_PROMPT_VERSION,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cached_tokens,
                max(usage.attempts, 1),
                usage.latency_ms,
            ),
        )


def _persist(connection: Any, answer: Answer) -> None:
    """Record the query and its citations (V001 `rag_query` / `rag_citation`).

    Writes the id back onto the answer so the client can address it later.
    """
    query_id = uuid.uuid4()
    answer.query_id = str(query_id)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO rag_query (id, question, retrieval_plan, answer_markdown,
                                   status, model_meta, metrics, limitations,
                                   completed_at)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, now())
            """,
            (
                query_id,
                answer.question,
                Json(answer.plan.as_dict() if answer.plan else {}),
                answer.answer_markdown,
                "REFUSED" if answer.refused else "ANSWERED",
                Json({"model": answer.model, "prompt_version": ANSWER_PROMPT_VERSION}),
                Json(answer.metrics),
                Json(answer.limitations),
            ),
        )
        if answer.citations:
            cursor.executemany(
                """
                INSERT INTO rag_citation (rag_query_id, citation_no, content_chunk_id,
                                          claim_text, support_score)
                VALUES (%s, %s, %s::uuid, %s, %s)
                """,
                [
                    (
                        query_id,
                        c.number,
                        c.chunk_id,
                        c.claim_text or answer.question,
                        c.support_score,
                    )
                    for c in answer.citations
                ],
            )
    connection.commit()

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
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Json

from ahr.config import get_settings
from ahr.processing.llm import LlmClient, LlmUnavailableError
from ahr.rag.answer import (
    ANSWER_PROMPT_VERSION,
    MAX_EVIDENCE,
    MAX_PARENT_CHARS,
    SYSTEM_PROMPT,
    Answer,
    bind_citations,
    build_user_prompt,
    check_invariants,
    load_evidence,
    parse_model_output,
    summarise_considered,
)
from ahr.rag.dimensions import Candidate, apply_dimensions
from ahr.rag.embeddings import EmbeddingClient
from ahr.rag.folding import fold_by_story, load_chunk_facts, main_source_first
from ahr.rag.fusion import apply_boosts, reciprocal_rank_fusion
from ahr.rag.parent import expand as expand_parent
from ahr.rag.planner import plan as build_plan
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
from ahr.rag.temporal import Scored, apply_temporal_fit

logger = logging.getLogger(__name__)

# B4 measured 40 as better than 100 on every metric and 3.2x faster.
RERANK_CANDIDATES = 40

# Called as each stage completes, so a caller can report progress while the
# query is still running. Optional: nothing in the pipeline depends on it, and
# the evaluation runs pass nothing.
StageReporter = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _noop_stage(name: str, detail: dict[str, Any]) -> None:
    return None


async def retrieve(
    connection: Any,
    question: str,
    *,
    embedder: EmbeddingClient,
    reranker: RerankClient | None,
    asked_at: datetime,
    on_stage: StageReporter | None = None,
) -> tuple[list[ChunkHit], Any, dict[str, Any]]:
    """The B4 pipeline, returning hits, the frozen plan, and what happened."""
    started = time.monotonic()
    stages: dict[str, int] = {}
    report = on_stage or _noop_stage

    async def mark(name: str, since: float, **detail: Any) -> None:
        stages[name] = int((time.monotonic() - since) * 1000)
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

    step = time.monotonic()
    vectors = await embedder.embed([question])
    await mark("embed", step)

    step = time.monotonic()
    dense = dense_search(connection, vectors[0], limit=VECTOR_PASSAGE_TOP_K, window=filter_window)
    await mark("dense", step, found=len(dense))

    step = time.monotonic()
    sparse = sparse_search(connection, question, limit=KEYWORD_FTS_TOP_K, window=filter_window)
    await mark("sparse", step, found=len(sparse))

    channels: dict[str, list[ChunkHit]] = {"dense": dense, "sparse": sparse}

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

    degraded: list[str] = []
    step = time.monotonic()
    if reranker is not None and hits:
        candidates = hits[:RERANK_CANDIDATES]
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

            taken = {h.chunk_id for h in reordered}
            hits = reordered + [h for h in hits if h.chunk_id not in taken]
        except RerankUnavailableError as exc:
            # §5 requires degradation to be recorded rather than silent. A dead
            # reranker costs ranking quality; it must not cost the answer.
            logger.warning("rerank unavailable, using fused order: %s", exc)
            degraded.append("rerank")
    elif reranker is None:
        degraded.append("rerank")
    await mark("rerank", step, degraded=bool(degraded))

    metrics = {
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
) -> tuple[list[str], dict[str, Any]]:
    """Turn a ranking into an evidence set: cap per document, then fold events.

    Two different redundancies, so two passes. The per-document cap stops one
    long release note filling every slot with its own paragraphs; story folding
    stops one *event* filling them with three outlets' coverage of it. Neither
    subsumes the other — the Anthropic incident was three separate documents.
    """
    capped: list[str] = []
    seen: dict[str, int] = {}
    for hit in hits:
        count = seen.get(hit.content_item_id, 0)
        if count >= per_item:
            continue
        seen[hit.content_item_id] = count + 1
        capped.append(hit.chunk_id)
        # Fold from a wider pool than the budget: passages dropped as duplicate
        # coverage have to be replaced by the next distinct thing, not simply
        # leave the evidence set short.
        if len(capped) >= limit * 3:
            break

    facts = load_chunk_facts(connection, capped)
    folded = fold_by_story(capped, facts, limit=limit)
    ordered = main_source_first(folded, facts)

    stats = {
        "candidates": len(capped),
        "after_story_folding": len(folded),
        "stories_folded": len(capped) - len(folded),
    }
    return ordered, stats


async def answer_question(
    question: str,
    *,
    embedder: EmbeddingClient,
    reranker: RerankClient | None,
    llm: LlmClient,
    asked_at: datetime | None = None,
    persist: bool = True,
    on_stage: StageReporter | None = None,
) -> Answer:
    """Answer one question, or refuse, and record what was cited."""
    moment = asked_at or datetime.now(UTC)
    started = time.monotonic()
    report = on_stage or _noop_stage

    with psycopg.connect(get_settings().database_url) as connection:
        hits, retrieval_plan, metrics = await retrieve(
            connection,
            question,
            embedder=embedder,
            reranker=reranker,
            asked_at=moment,
            on_stage=on_stage,
        )
        step = time.monotonic()
        chunk_ids, selection_stats = select_evidence(connection, hits)
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
            raw, usage = await llm.summarize(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(question, evidence, retrieval_plan),
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
                "total_ms": int((time.monotonic() - started) * 1000),
                "prompt_version": ANSWER_PROMPT_VERSION,
            }
        )

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
        return result


HISTORY_LIMIT = 20


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
            """
            SELECT q.id::text, q.question, q.answer_markdown, q.status,
                   q.retrieval_plan, q.metrics, q.completed_at,
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
                               'independentSources', COALESCE(st.independent_source_count, 1)
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
             GROUP BY q.id
             ORDER BY q.completed_at DESC NULLS LAST
             LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    return [
        {
            "queryId": row[0],
            "question": row[1],
            "answerMarkdown": row[2] or "",
            "refused": row[3] == "REFUSED",
            "refusalReason": "检索到的内容不足以回答这个问题" if row[3] == "REFUSED" else None,
            "limitations": [],
            "plan": row[4] or {},
            "metrics": row[5] or {},
            "askedAt": row[6].isoformat() if row[6] else None,
            "citations": row[7] or [],
            # Not persisted: `considered` is a retrieval-time view, and storing
            # it would duplicate rows that already exist as content_item.
            "considered": [],
        }
        for row in rows
    ]


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
                                   status, model_meta, metrics, completed_at)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, now())
            """,
            (
                query_id,
                answer.question,
                Json(answer.plan.as_dict() if answer.plan else {}),
                answer.answer_markdown,
                "REFUSED" if answer.refused else "ANSWERED",
                Json({"model": answer.model, "prompt_version": ANSWER_PROMPT_VERSION}),
                Json(answer.metrics),
            ),
        )
        if answer.citations:
            cursor.executemany(
                """
                INSERT INTO rag_citation (rag_query_id, citation_no, content_chunk_id,
                                          claim_text, support_score)
                VALUES (%s, %s, %s::uuid, %s, NULL)
                """,
                [
                    (query_id, c.number, c.chunk_id, c.claim_text or answer.question)
                    for c in answer.citations
                ],
            )
    connection.commit()

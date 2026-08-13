"""One-snapshot A/B for the Chinese-vendor specialist set.

The earlier ENTITY run proved that ``entity_temporal`` changed the unfused
candidate set, but it was compared with an older run and never passed through
the cross-encoder.  HNSW insertions can move Recall by about two points between
days, so that comparison cannot attribute a small delta to code.

This runner embeds each question once and captures dense, sparse, generic
temporal and entity-temporal channels in one process.  Four arms are then
derived from that immutable capture:

* ``control``: dense + sparse + generic temporal;
* ``entity``: dense + sparse + entity-temporal (the shipped path);
* ``noise``: the entity arm plus human-selected, real distractor passages.
* ``summary_hint``: the entity arm with an explicitly untrusted Chinese summary
  visible only to the cross-encoder; generated facts never enter evidence;
* ``identifier_guard``: the entity arm with a bounded post-rank boost when an
  explicit model/version identifier from the question occurs in the passage.

All arms use the same configured cross-encoder and production B7/B9 post-rank
dimensions.  The report stores channel order, arm candidates, model names and a
SHA-256 snapshot hash so a delta is diagnosable rather than anecdotal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from ahr.rag.dimensions import IDENTIFIER_FIT_WEIGHT
from ahr.rag.embeddings import EmbeddingClient
from ahr.rag.eval.golden import GoldenQuestion, GoldenSet
from ahr.rag.eval.metrics import dedupe_hits_to_items
from ahr.rag.eval.runner import (
    EPOCH,
    EvalReport,
    QuestionResult,
    _apply_dimensions,
    _apply_temporal_fit,
    _score,
    snapshot_window,
)
from ahr.rag.fusion import apply_boosts, reciprocal_rank_fusion
from ahr.rag.planner import plan
from ahr.rag.rerank import RerankClient
from ahr.rag.retrieval import (
    KEYWORD_FTS_TOP_K,
    TEMPORAL_SQL_TOP_K,
    VECTOR_PASSAGE_TOP_K,
    ChunkHit,
    dense_search,
    entity_names,
    expand_vendor_aliases,
    expand_vendor_entity_ids,
    load_chunk_texts,
    load_item_metadata,
    resolve_query_entities,
    sparse_search,
    temporal_search,
)


def _snapshot_hash(payload: list[dict[str, Any]]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _merge_distractors(candidates: list[ChunkHit], distractors: list[ChunkHit]) -> list[ChunkHit]:
    """Put annotated distractors inside the rerank budget without duplicates.

    Input order is not a relevance signal to a cross-encoder.  Putting the
    distractors first only guarantees they are scored when the fused candidate
    list already fills the budget; the model must still earn their final rank.
    """
    merged: list[ChunkHit] = []
    seen: set[str] = set()
    for hit in [*distractors, *candidates]:
        if hit.chunk_id in seen:
            continue
        seen.add(hit.chunk_id)
        merged.append(hit)
    return merged


def _load_distractor_hits(
    connection: Any, question: GoldenQuestion, *, asked_at: datetime
) -> list[ChunkHit]:
    if not question.distractor_ids:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (ci.id)
                   ch.id::text, ci.id::text, COALESCE(ci.zh_title, ci.title),
                   s.name, s.id, s.source_tier
              FROM content_item ci
              JOIN content_revision cr ON cr.id = ci.current_revision_id
              JOIN content_chunk ch ON ch.content_revision_id = cr.id
              JOIN source s ON s.id = ci.source_id
             WHERE ci.id = ANY(%s::uuid[])
               AND ch.is_active
               AND ci.duplicate_of_id IS NULL
               AND COALESCE(ci.published_at, ci.observed_at) <= %s
             ORDER BY ci.id, ch.ordinal
            """,
            (sorted(question.distractor_ids), asked_at),
        )
        return [
            ChunkHit(
                chunk_id=str(row[0]),
                content_item_id=str(row[1]),
                score=0.0,
                title=str(row[2] or ""),
                source_name=str(row[3] or ""),
                source_id=str(row[4] or ""),
                source_tier=str(row[5] or ""),
                channels=("annotated_distractor",),
            )
            for row in cursor.fetchall()
        ]


def _fuse(
    connection: Any,
    channels: dict[str, list[ChunkHit]],
    *,
    question: str,
    asked_at: datetime,
    query_entities: frozenset[str],
) -> list[ChunkHit]:
    retrieval_plan = plan(question, asked_at=asked_at)
    window = (
        (retrieval_plan.time_range.start, retrieval_plan.time_range.end)
        if retrieval_plan.time_range
        else None
    )
    fused = reciprocal_rank_fusion(channels)
    metadata = load_item_metadata(connection, sorted({hit.content_item_id for hit in fused}))
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
            source_id=hit.source_id,
            source_tier=hit.source_tier,
            channels=hit.channels,
        )
        for hit in fused
    ]


async def _rerank(
    connection: Any,
    reranker: RerankClient,
    question: GoldenQuestion,
    candidates: list[ChunkHit],
    *,
    candidate_limit: int,
    top_n: int,
    include_summary_hint: bool = False,
    identifier_fit_weight: float = 0.0,
) -> list[ChunkHit]:
    head = candidates[:candidate_limit]
    if not head:
        return []
    texts = load_chunk_texts(connection, [hit.chunk_id for hit in head])
    if include_summary_hint:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ch.id::text, ci.summary_zh
                  FROM content_chunk ch
                  JOIN content_revision cr ON cr.id = ch.content_revision_id
                  JOIN content_item ci ON ci.id = cr.content_item_id
                 WHERE ch.id = ANY(%s::uuid[])
                   AND ci.summary_zh IS NOT NULL
                """,
                ([hit.chunk_id for hit in head],),
            )
            summaries = {str(row[0]): str(row[1]) for row in cursor.fetchall() if row[1]}
        texts = {
            chunk_id: (
                f"[UNTRUSTED RETRIEVAL HINT — NEVER EVIDENCE]\n{summaries[chunk_id]}\n\n{document}"
                if chunk_id in summaries
                else document
            )
            for chunk_id, document in texts.items()
        }
    scored = await reranker.rerank(
        question.question,
        [texts.get(hit.chunk_id, hit.title) for hit in head],
        top_n=top_n,
    )
    reordered = [
        ChunkHit(
            chunk_id=head[index].chunk_id,
            content_item_id=head[index].content_item_id,
            score=score,
            title=head[index].title,
            source_name=head[index].source_name,
            source_id=head[index].source_id,
            source_tier=head[index].source_tier,
            channels=head[index].channels,
        )
        for index, score in scored
    ]
    reordered = _apply_dimensions(
        connection,
        reordered,
        question.question,
        question.asked_at,
        passages=texts,
        identifier_fit_weight=identifier_fit_weight,
    )
    reordered = _apply_temporal_fit(connection, reordered, question.question, question.asked_at)
    taken = {hit.chunk_id for hit in reordered}
    return reordered + [hit for hit in candidates if hit.chunk_id not in taken]


def _arm_report(
    name: str,
    golden: GoldenSet,
    rows: list[QuestionResult],
    *,
    run_id: str,
    config: dict[str, Any],
) -> EvalReport:
    return EvalReport(
        run_id=f"{run_id}-{name}",
        config={"variant": f"specialist-{name}", "golden_questions": len(golden), **config},
        questions=rows,
    )


def _delta(
    entity: EvalReport,
    control: EvalReport,
    noise: EvalReport,
    summary_hint: EvalReport,
    identifier_guard: EvalReport,
) -> dict[str, float]:
    entity_overall = entity.summary()["overall"]
    control_overall = control.summary()["overall"]
    noise_overall = noise.summary()["overall"]
    summary_hint_overall = summary_hint.summary()["overall"]
    identifier_guard_overall = identifier_guard.summary()["overall"]
    return {
        "entity_vs_control_recall@10": round(
            entity_overall["recall@10"] - control_overall["recall@10"], 4
        ),
        "entity_vs_control_recall@20": round(
            entity_overall["recall@20"] - control_overall["recall@20"], 4
        ),
        "noise_vs_entity_recall@10": round(
            noise_overall["recall@10"] - entity_overall["recall@10"], 4
        ),
        "noise_vs_entity_recall@20": round(
            noise_overall["recall@20"] - entity_overall["recall@20"], 4
        ),
        "summary_hint_vs_entity_recall@10": round(
            summary_hint_overall["recall@10"] - entity_overall["recall@10"], 4
        ),
        "summary_hint_vs_entity_recall@20": round(
            summary_hint_overall["recall@20"] - entity_overall["recall@20"], 4
        ),
        "identifier_guard_vs_entity_recall@10": round(
            identifier_guard_overall["recall@10"] - entity_overall["recall@10"], 4
        ),
        "identifier_guard_vs_entity_recall@20": round(
            identifier_guard_overall["recall@20"] - entity_overall["recall@20"], 4
        ),
    }


async def run_specialist_ab(
    connection: Any,
    golden: GoldenSet,
    embedding: EmbeddingClient,
    reranker: RerankClient,
    *,
    candidate_limit: int = 40,
    top_n: int = 24,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run all three arms and return a replayable report."""
    resolved_run_id = run_id or datetime.now(UTC).strftime("SPECIALIST-%Y%m%dT%H%M%SZ")
    control_rows: list[QuestionResult] = []
    entity_rows: list[QuestionResult] = []
    noise_rows: list[QuestionResult] = []
    summary_hint_rows: list[QuestionResult] = []
    identifier_guard_rows: list[QuestionResult] = []
    snapshots: list[dict[str, Any]] = []

    for question in golden.questions:
        retrieval_plan = plan(question.question, asked_at=question.asked_at)
        vectors = await embedding.embed([question.question])
        window = (
            (retrieval_plan.time_range.start, retrieval_plan.time_range.end)
            if retrieval_plan.time_range
            else None
        )
        filter_window = snapshot_window(
            question.asked_at, window if retrieval_plan.freshness_required else None
        )
        query_entities = resolve_query_entities(connection, question.question)
        family_entities = expand_vendor_entity_ids(connection, query_entities)
        aliases = expand_vendor_aliases(connection, query_entities)
        names = entity_names(connection, query_entities)

        dense = dense_search(
            connection, vectors[0], limit=VECTOR_PASSAGE_TOP_K, window=filter_window
        )
        sparse = sparse_search(
            connection,
            question.question,
            limit=KEYWORD_FTS_TOP_K,
            window=filter_window,
            extra_terms=aliases,
            entity_terms=names + aliases,
        )
        generic_temporal: list[ChunkHit] = []
        entity_temporal: list[ChunkHit] = []
        if window is not None:
            fixed_window = snapshot_window(question.asked_at, window)
            generic_temporal = temporal_search(
                connection, window=fixed_window, limit=TEMPORAL_SQL_TOP_K
            )
            if family_entities:
                entity_temporal = temporal_search(
                    connection,
                    window=fixed_window,
                    limit=TEMPORAL_SQL_TOP_K,
                    entity_ids=family_entities,
                )

        control_channels = {"dense": dense, "sparse": sparse}
        entity_channels = {"dense": dense, "sparse": sparse}
        if generic_temporal:
            control_channels["temporal"] = generic_temporal
        if entity_temporal:
            entity_channels["entity_temporal"] = entity_temporal
        elif generic_temporal:
            entity_channels["temporal"] = generic_temporal

        control_candidates = _fuse(
            connection,
            control_channels,
            question=question.question,
            asked_at=question.asked_at,
            query_entities=family_entities,
        )
        entity_candidates = _fuse(
            connection,
            entity_channels,
            question=question.question,
            asked_at=question.asked_at,
            query_entities=family_entities,
        )
        distractors = _load_distractor_hits(connection, question, asked_at=question.asked_at)
        noise_candidates = _merge_distractors(entity_candidates, distractors)

        control_ranked = await _rerank(
            connection,
            reranker,
            question,
            control_candidates,
            candidate_limit=candidate_limit,
            top_n=top_n,
        )
        entity_ranked = await _rerank(
            connection,
            reranker,
            question,
            entity_candidates,
            candidate_limit=candidate_limit,
            top_n=top_n,
        )
        noise_ranked = await _rerank(
            connection,
            reranker,
            question,
            noise_candidates,
            candidate_limit=candidate_limit,
            top_n=top_n,
        )
        summary_hint_ranked = await _rerank(
            connection,
            reranker,
            question,
            entity_candidates,
            candidate_limit=candidate_limit,
            top_n=top_n,
            include_summary_hint=True,
        )
        identifier_guard_ranked = await _rerank(
            connection,
            reranker,
            question,
            entity_candidates,
            candidate_limit=candidate_limit,
            top_n=top_n,
            identifier_fit_weight=IDENTIFIER_FIT_WEIGHT,
        )

        for ranked, target in (
            (control_ranked, control_rows),
            (entity_ranked, entity_rows),
            (noise_ranked, noise_rows),
            (summary_hint_ranked, summary_hint_rows),
            (identifier_guard_ranked, identifier_guard_rows),
        ):
            items = dedupe_hits_to_items(ranked)
            target.append(
                _score(question, items, top_chunk_score=ranked[0].score if ranked else 0.0)
            )

        snapshots.append(
            {
                "question_id": question.id,
                "question": question.question,
                "asked_at": question.asked_at.isoformat(),
                "relevant_item_ids": sorted(question.relevant_ids),
                "distractor_item_ids": sorted(question.distractor_ids),
                "resolved_entity_ids": sorted(query_entities),
                "expanded_entity_ids": sorted(family_entities),
                "channels": {
                    "dense": [hit.chunk_id for hit in dense],
                    "sparse": [hit.chunk_id for hit in sparse],
                    "temporal": [hit.chunk_id for hit in generic_temporal],
                    "entity_temporal": [hit.chunk_id for hit in entity_temporal],
                },
                "arm_candidate_ids": {
                    "control": [hit.chunk_id for hit in control_candidates[:candidate_limit]],
                    "entity": [hit.chunk_id for hit in entity_candidates[:candidate_limit]],
                    "noise": [hit.chunk_id for hit in noise_candidates[:candidate_limit]],
                },
                "arm_top_item_ids": {
                    "control": [row.item_id for row in dedupe_hits_to_items(control_ranked)[:20]],
                    "entity": [row.item_id for row in dedupe_hits_to_items(entity_ranked)[:20]],
                    "noise": [row.item_id for row in dedupe_hits_to_items(noise_ranked)[:20]],
                    "summary_hint": [
                        row.item_id for row in dedupe_hits_to_items(summary_hint_ranked)[:20]
                    ],
                    "identifier_guard": [
                        row.item_id for row in dedupe_hits_to_items(identifier_guard_ranked)[:20]
                    ],
                },
            }
        )

    config = {
        "embedding_model": embedding.model_name,
        "reranker_model": reranker.model_name,
        "candidate_limit": candidate_limit,
        "top_n": top_n,
        "snapshot_window_floor": EPOCH.isoformat(),
    }
    control_report = _arm_report(
        "control", golden, control_rows, run_id=resolved_run_id, config=config
    )
    entity_report = _arm_report(
        "entity", golden, entity_rows, run_id=resolved_run_id, config=config
    )
    noise_report = _arm_report("noise", golden, noise_rows, run_id=resolved_run_id, config=config)
    summary_hint_report = _arm_report(
        "summary-hint", golden, summary_hint_rows, run_id=resolved_run_id, config=config
    )
    identifier_guard_report = _arm_report(
        "identifier-guard", golden, identifier_guard_rows, run_id=resolved_run_id, config=config
    )
    entity_overall = entity_report.summary()["overall"]
    query_rewrite_trial_required = entity_overall["recall@20"] < 0.85

    return {
        "run_id": resolved_run_id,
        "config": config,
        "snapshot_sha256": _snapshot_hash(snapshots),
        "summaries": {
            "control": control_report.summary(),
            "entity": entity_report.summary(),
            "noise": noise_report.summary(),
            "summary_hint": summary_hint_report.summary(),
            "identifier_guard": identifier_guard_report.summary(),
        },
        "deltas": _delta(
            entity_report,
            control_report,
            noise_report,
            summary_hint_report,
            identifier_guard_report,
        ),
        "decision": {
            "locked_recall_at_20_gate": 0.85,
            "entity_recall_at_20_passed": entity_overall["recall@20"] >= 0.85,
            "query_rewrite_trial_required": query_rewrite_trial_required,
            "reason": (
                "specialist Recall@20 is below AHR-QSO-700 §8"
                if query_rewrite_trial_required
                else "specialist Recall@20 passes; do not add an extra LLM rewrite round trip"
            ),
        },
        "rerank_usage": asdict(reranker.usage),
        "channel_snapshot_sha256": _snapshot_hash(
            [{"question_id": row["question_id"], "channels": row["channels"]} for row in snapshots]
        ),
        "questions": snapshots,
        "arm_results": {
            "control": [asdict(row) for row in control_rows],
            "entity": [asdict(row) for row in entity_rows],
            "noise": [asdict(row) for row in noise_rows],
            "summary_hint": [asdict(row) for row in summary_hint_rows],
            "identifier_guard": [asdict(row) for row in identifier_guard_rows],
        },
    }

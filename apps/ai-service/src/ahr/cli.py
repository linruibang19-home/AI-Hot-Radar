"""Operational entry points for the AI service.

Run inside the container so DATABASE_URL resolves through the Compose network:

    docker compose exec ai-service python -m ahr.cli sync-sources
    docker compose exec ai-service python -m ahr.cli probe --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
import yaml

from ahr.config import get_settings
from ahr.ingestion.registry import load_sources, summarize, sync_sources
from ahr.observability import configure_logging

if TYPE_CHECKING:
    # Type-only, so the eval modules are still imported lazily inside the
    # commands that need them — importing them at module load would pull the
    # embedding and rerank clients into every `sync-sources` run.
    from ahr.rag.eval.golden import GoldenSet

DEFAULT_SOURCES_PATH = Path("/app/config/sources.yaml")


def cmd_sync_sources(args: argparse.Namespace) -> int:
    sources = load_sources(args.path)
    summary = summarize(sources)

    with psycopg.connect(get_settings().database_url) as connection:
        written = sync_sources(connection, sources, config_version=args.config_version)
        connection.commit()

    print(
        json.dumps(
            {
                "written": written,
                "total": summary.total,
                "enabled": summary.enabled,
                "disabled": summary.disabled,
                "by_profile": summary.by_profile,
            },
            indent=2,
        )
    )
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    from ahr.ingestion.probe import run_probe

    return asyncio.run(run_probe(limit=args.limit, profile=args.profile, output=args.output))


def cmd_ingest(args: argparse.Namespace) -> int:
    from ahr.ingestion.pipeline import run_ingest

    return asyncio.run(
        run_ingest(
            limit=args.limit,
            profile=args.profile,
            source_id=args.source,
            max_documents=args.max_documents,
            output=args.output,
        )
    )


def cmd_process(args: argparse.Namespace) -> int:
    from ahr.processing.pipeline import process_pending

    stats = asyncio.run(process_pending(limit=args.limit, enrich=not args.no_enrich))
    print(json.dumps(stats.__dict__, indent=2, ensure_ascii=False))
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    import psycopg

    from ahr.ingestion.scheduler import run_forever, run_tick, schedule_summary, seed_poll_schedule

    with psycopg.connect(get_settings().database_url) as connection:
        seeded = seed_poll_schedule(connection)
        print(json.dumps({"seeded": seeded, **schedule_summary(connection)}, indent=2))

    if args.once:
        result = asyncio.run(run_tick(batch_size=args.batch_size, max_documents=args.max_documents))
        print(json.dumps(result.__dict__, indent=2))
        return 0

    asyncio.run(
        run_forever(
            interval_seconds=args.interval,
            batch_size=args.batch_size,
            max_documents=args.max_documents,
        )
    )
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    import psycopg

    from ahr.processing.selection import select_for_days

    with psycopg.connect(get_settings().database_url) as connection:
        result = select_for_days(connection, days=args.days)
    print(json.dumps(result, indent=2))
    return 0


def cmd_backfill_support(args: argparse.Namespace) -> int:
    """Score citations written before support scoring existed.

    `rag_citation.support_score` was defined in V001 and filled by nothing until
    2026-08-07, so the rows already in the table carry NULL. NULL means "not
    scored" everywhere it is read, which is correct but leaves most of the
    history unexplained on a page whose point is that every claim is checkable.

    Scored with the same cross-encoder the live path and the offline evaluation
    use — a third method would produce a number that is not comparable with
    either.
    """
    import asyncio

    from ahr.rag.rerank import RerankUnavailableError
    from ahr.rag.rerank import build_client_from_env as build_reranker
    from ahr.rag.support import backfill

    async def run() -> dict[str, object]:
        try:
            reranker = build_reranker()
        except RerankUnavailableError as exc:
            return {"error": str(exc)}

        async with reranker:
            with psycopg.connect(get_settings().database_url) as connection:
                return await backfill(connection, reranker, limit=args.limit)

    print(json.dumps(asyncio.run(run()), indent=2, ensure_ascii=False))
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    """Report actual LLM spend from recorded provider usage."""
    with psycopg.connect(get_settings().database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT model,
                   count(*),
                   sum(prompt_tokens), sum(completion_tokens), sum(cached_tokens),
                   sum(attempts), count(*) FILTER (WHERE NOT succeeded),
                   round(avg(latency_ms))
              FROM llm_usage
             WHERE created_at > now() - (%s || ' days')::interval
             GROUP BY model
            """,
            (args.days,),
        )
        rows = cursor.fetchall()

    report = [
        {
            "model": r[0],
            "calls": r[1],
            "prompt_tokens": int(r[2] or 0),
            "completion_tokens": int(r[3] or 0),
            "cached_tokens": int(r[4] or 0),
            "total_tokens": int((r[2] or 0) + (r[3] or 0)),
            "attempts": int(r[5] or 0),
            "failed": r[6],
            "avg_latency_ms": int(r[7] or 0),
        }
        for r in rows
    ]
    print(json.dumps({"days": args.days, "usage": report}, indent=2, ensure_ascii=False))
    return 0


def cmd_heat(args: argparse.Namespace) -> int:
    from ahr.processing.heat import rescore

    with psycopg.connect(get_settings().database_url) as connection:
        print(json.dumps(rescore(connection, days=args.days), indent=2))
    return 0


def cmd_cluster(args: argparse.Namespace) -> int:
    from ahr.processing.story_repository import recluster, sync_item_heat

    with psycopg.connect(get_settings().database_url) as connection:
        result = recluster(connection, days=args.days)
        result["items_rescored"] = sync_item_heat(connection)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    """Run the downstream pipeline once, or on a loop.

    Ingestion has its own scheduler; this is everything after it. Without it the
    site keeps collecting content and stops showing it.
    """
    from ahr.processing.worker import run_forever, run_once

    if args.once:
        result = asyncio.run(
            run_once(
                process_limit=args.process_limit,
                reason_limit=args.reason_limit,
                with_reports=not args.no_reports,
            )
        )
        print(json.dumps(result.__dict__, indent=2, ensure_ascii=False, default=str))
        return 0

    asyncio.run(
        run_forever(
            interval_seconds=args.interval,
            process_limit=args.process_limit,
            reason_limit=args.reason_limit,
            with_reports=not args.no_reports,
        )
    )
    return 0


def cmd_fix_titles(args: argparse.Namespace) -> int:
    """Re-apply title sanitising to rows already stored.

    Re-ingesting only repairs items still on their source's listing page; an
    article that has scrolled off keeps its bad title forever. This walks stored
    rows instead, using the body we already have.
    """
    from ahr.ingestion.titles import resolve_title

    fixed = 0
    inspected = 0
    with psycopg.connect(get_settings().database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ci.id, ci.title, ci.canonical_url, cr.body_text
                  FROM content_item ci
                  LEFT JOIN content_revision cr ON cr.id = ci.current_revision_id
                 WHERE ci.duplicate_of_id IS NULL
                """
            )
            rows = cursor.fetchall()

        for item_id, title, canonical, body in rows:
            inspected += 1
            resolved = resolve_title(title, body_text=body, fallback=canonical) or canonical
            if resolved == title:
                continue
            if args.dry_run:
                print(f"{title[:60]!r}\n  -> {resolved[:60]!r}")
            else:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE content_item SET title = %s WHERE id = %s",
                        (resolved[:500], item_id),
                    )
                    cursor.execute(
                        "UPDATE content_revision SET title = %s WHERE content_item_id = %s",
                        (resolved[:500], item_id),
                    )
            fixed += 1

        if not args.dry_run:
            connection.commit()

    print(json.dumps({"inspected": inspected, "fixed": fixed, "dry_run": args.dry_run}, indent=2))
    return 0


def cmd_rechunk(args: argparse.Namespace) -> int:
    """Re-split every stored revision with the current chunker.

    Chunking rules changed (short-fragment merging and a hard size cap), and the
    stored chunks predate them. Re-running the ingest pipeline would not do this:
    it only processes items in PENDING, and every item here is already ENRICHED.

    Embeddings are cleared for rewritten revisions so the next `embed` run
    regenerates them — a vector left attached to replaced text points at content
    that no longer exists.
    """
    from ahr.processing.chunking import HARD_MAX_TOKENS
    from ahr.processing.pipeline import chunk_revision

    before = 0
    after = 0
    revisions = 0

    with psycopg.connect(get_settings().database_url) as connection:
        with connection.cursor() as cursor:
            oversized_filter = (
                """
                 AND EXISTS (
                        SELECT 1 FROM content_chunk cc
                        WHERE cc.content_revision_id = cr.id
                          AND cc.is_active
                          AND cc.token_count > %s
                 )
                """
                if args.oversized_only
                else ""
            )
            params = (HARD_MAX_TOKENS,) if args.oversized_only else ()
            cursor.execute(
                f"""
                SELECT cr.id, cr.body_text
                  FROM content_revision cr
                  JOIN content_item ci ON ci.current_revision_id = cr.id
                 WHERE cr.body_text IS NOT NULL AND length(cr.body_text) > 0
                   {oversized_filter}
                 ORDER BY cr.created_at
                """,
                params,
            )
            rows = cursor.fetchall()

        for revision_id, body in rows:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM content_chunk"
                    " WHERE content_revision_id = %s AND is_active",
                    (revision_id,),
                )
                row = cursor.fetchone()
                before += int(row[0]) if row else 0

            written = chunk_revision(connection, revision_id, body)
            after += written
            revisions += 1

        connection.commit()

    print(
        json.dumps(
            {
                "revisions": revisions,
                "chunks_before": before,
                "chunks_after": after,
                "oversized_only": args.oversized_only,
            },
            indent=2,
        )
    )
    return 0


def cmd_embed(args: argparse.Namespace) -> int:
    """Populate content_chunk.embedding for the retrieval index (M4)."""
    from ahr.rag.backfill import backfill_embeddings
    from ahr.rag.embeddings import EmbeddingUnavailableError, build_client_from_env

    async def run() -> dict[str, object]:
        try:
            client = build_client_from_env()
        except EmbeddingUnavailableError as exc:
            return {"error": str(exc)}
        async with client:
            with psycopg.connect(get_settings().database_url) as connection:
                return await backfill_embeddings(
                    connection, client=client, limit=args.limit, batch_size=args.batch_size
                )

    print(json.dumps(asyncio.run(run()), indent=2, ensure_ascii=False))
    return 0


def cmd_rag_eval(args: argparse.Namespace) -> int:
    """Score a retrieval configuration against the golden set (TASK-M4-001)."""
    from ahr.rag.embeddings import EmbeddingUnavailableError, build_client_from_env
    from ahr.rag.eval.golden import (
        GoldenSet,
        GoldenSetError,
        describe_corpus_snapshot,
        load_golden_set,
        verify_items_exist,
        verify_original_evidence,
    )
    from ahr.rag.eval.runner import (
        dense_retriever,
        rerank_retriever,
        rrf_retriever,
        run_variant,
        sparse_retriever,
        union_retriever,
    )
    from ahr.rag.rerank import RerankUnavailableError
    from ahr.rag.rerank import build_client_from_env as build_reranker_from_env

    directory = Path(args.golden)
    try:
        golden = load_golden_set(directory, require_full=not args.allow_partial)
    except GoldenSetError as exc:
        print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        return 1

    if args.question_id:
        selected = tuple(
            question for question in golden.questions if question.id == args.question_id
        )
        if not selected:
            print(
                json.dumps(
                    {"error": f"question id not found: {args.question_id}"},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 1
        golden = GoldenSet(questions=selected, source_files=golden.source_files)

    if args.variant == "query-type-sweep":
        return _run_query_type_sweep(golden, args)

    if args.variant == "planner-diff":
        return _run_planner_diff(golden, args)

    if args.variant == "planner":
        # Before the connection, not after: the planner is pure functions over
        # the question and `asked_at`, so this variant runs with no database and
        # no provider — which is what lets it go in CI, where neither exists.
        # Dispatching after `psycopg.connect` would have quietly made that false.
        return _run_planner_eval(golden, args)

    with psycopg.connect(get_settings().database_url) as connection:
        missing = verify_items_exist(connection, golden)
        snapshot = describe_corpus_snapshot(connection, golden)

    if missing and not args.skip_unusable:
        # Annotations pointing at rows that are absent, superseded, or have no
        # chunks would depress every metric for a reason that has nothing to do
        # with retrieval quality. Refusing is what turned "citation precision is
        # low" into "1.4% of the corpus was never chunked".
        print(
            json.dumps(
                {
                    "error": "annotated items not usable",
                    "items": missing,
                    "hint": "fix the corpus, or pass --skip-unusable to exclude"
                    " the affected questions and record why",
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1

    if missing:
        # Proceeding is a deliberate act, and the exclusion is recorded in the
        # report rather than quietly shrinking the question count.
        unusable = set(missing)
        kept = tuple(q for q in golden.questions if not (q.relevant_ids & unusable))
        print(
            json.dumps(
                {
                    "warning": "excluding questions whose annotations are unusable",
                    "items": missing,
                    "questions_excluded": len(golden.questions) - len(kept),
                },
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        golden = replace(golden, questions=kept)

    if args.validate:
        from ahr.rag.eval.freshness import check as check_freshness
        from ahr.rag.eval.golden import CATEGORIES

        # Structural validity was the only thing checked here, and it is the
        # half that cannot rot: the YAML parses and the ids are well formed.
        # Whether those ids still point at retrievable content is the half that
        # decides if last week's numbers still mean anything.
        with psycopg.connect(get_settings().database_url) as connection:
            freshness = check_freshness(connection, golden)
            evidence_issues = verify_original_evidence(connection, golden)

        print(
            json.dumps(
                {
                    "valid": True,
                    "questions": len(golden),
                    "files": list(golden.source_files),
                    "by_category": {c: len(golden.by_category(c)) for c in CATEGORIES},
                    "annotated_items": len(golden.item_ids),
                    "annotated_distractors": len(
                        {item_id for q in golden.questions for item_id in q.distractor_ids}
                    ),
                    "original_evidence_issues": evidence_issues,
                    "freshness": freshness,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        # Non-zero when the annotations no longer describe the corpus, so this
        # can gate a scheduled run. Reporting a clean exit while pointing at
        # missing items would make the check decorative.
        return 1 if freshness["missing"] or freshness["unretrievable"] or evidence_issues else 0

    if args.variant in ("generation", "latency"):
        return _run_generation_eval(golden, args, snapshot)

    if args.variant == "sweep":
        return _run_weight_sweep(golden, args, snapshot)

    async def run() -> dict[str, object]:
        # The sparse channel needs no embedding provider at all, so a
        # sparse-only run stays available when the provider is down or out of
        # quota — which is also what makes it a usable degradation path.
        planner_llm = None
        if getattr(args, "llm_planner", False):
            from ahr.processing.llm import build_client_from_env as build_llm

            planner_llm = build_llm()

        client = None
        if args.variant != "b2-sparse":
            try:
                client = build_client_from_env()
            except EmbeddingUnavailableError as exc:
                return {"error": str(exc)}

        with psycopg.connect(get_settings().database_url) as connection:
            if args.variant == "specialist-ab":
                assert client is not None
                from ahr.rag.eval.specialist_ab import run_specialist_ab

                try:
                    reranker = build_reranker_from_env()
                except RerankUnavailableError as exc:
                    return {"error": str(exc)}
                async with client, reranker:
                    payload = await run_specialist_ab(
                        connection,
                        golden,
                        client,
                        reranker,
                        candidate_limit=args.rerank_candidates,
                        top_n=args.rerank_top_n,
                    )
                payload["config"]["corpus_snapshot"] = snapshot
                if args.output:
                    Path(args.output).write_text(
                        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                return payload
            if args.variant == "b1":
                assert client is not None
                async with client:
                    report = await run_variant(
                        golden,
                        dense_retriever(connection, client, chunk_depth=args.chunk_depth),
                        variant="B1-dense-only",
                        config={
                            "embedding_model": client.model_name,
                            "chunk_depth": args.chunk_depth,
                        },
                    )
            elif args.variant == "b2-sparse":
                report = await run_variant(
                    golden,
                    sparse_retriever(connection, chunk_depth=args.sparse_depth),
                    variant="B2-sparse-only",
                    config={"sparse_depth": args.sparse_depth},
                )
            elif args.variant == "b2-union":
                assert client is not None
                async with client:
                    report = await run_variant(
                        golden,
                        union_retriever(
                            connection,
                            client,
                            dense_depth=args.chunk_depth,
                            sparse_depth=args.sparse_depth,
                        ),
                        variant="B2-union-interleave",
                        config={
                            "embedding_model": client.model_name,
                            "chunk_depth": args.chunk_depth,
                            "sparse_depth": args.sparse_depth,
                            "merge": "round-robin interleave (RRF lands in B3)",
                        },
                    )
            elif args.variant in ("b4-rerank", "b7-temporal-fit", "b9-dimensions"):
                assert client is not None
                try:
                    reranker = build_reranker_from_env()
                except RerankUnavailableError as exc:
                    return {"error": str(exc)}
                async with client, reranker:
                    if planner_llm is not None:
                        await planner_llm.__aenter__()
                    report = await run_variant(
                        golden,
                        rerank_retriever(
                            connection,
                            client,
                            reranker,
                            dense_depth=args.chunk_depth,
                            sparse_depth=args.sparse_depth,
                            candidate_limit=args.rerank_candidates,
                            top_n=args.rerank_top_n,
                            llm=planner_llm,
                            # B9 keeps temporal_fit on: it is the shipped
                            # configuration, so the comparison isolates the two
                            # new dimensions rather than also removing B7.
                            use_temporal_fit=args.variant
                            in (
                                "b7-temporal-fit",
                                "b9-dimensions",
                            ),
                            use_dimensions=args.variant == "b9-dimensions",
                            weights=_parse_weights(args.weights),
                        ),
                        variant=(
                            "B9-dimensions"
                            if args.variant == "b9-dimensions"
                            else "B7-temporal-fit"
                            if args.variant == "b7-temporal-fit"
                            else f"B4-rerank-{args.rerank_candidates}"
                        ),
                        config={
                            "embedding_model": client.model_name,
                            "reranker_model": reranker.model_name,
                            "chunk_depth": args.chunk_depth,
                            "sparse_depth": args.sparse_depth,
                            "rerank_top_n": args.rerank_top_n,
                            "rerank_candidates": args.rerank_candidates,
                            "fusion_weights": _parse_weights(args.weights) or "default",
                        },
                    )
                    report.config["rerank_usage"] = {
                        "calls": reranker.usage.calls,
                        "documents": reranker.usage.documents,
                        "latency_ms_total": reranker.usage.latency_ms,
                        "failures": reranker.usage.failures,
                    }
            else:
                # b3-rrf, and b3-no-temporal which isolates the temporal
                # channel's own contribution from the fusion's.
                assert client is not None
                use_temporal = args.variant != "b3-no-temporal"
                async with client:
                    report = await run_variant(
                        golden,
                        rrf_retriever(
                            connection,
                            client,
                            dense_depth=args.chunk_depth,
                            sparse_depth=args.sparse_depth,
                            use_temporal=use_temporal,
                            llm=planner_llm,
                        ),
                        variant=("B3-rrf" if use_temporal else "B3-rrf-without-temporal"),
                        config={
                            "embedding_model": client.model_name,
                            "chunk_depth": args.chunk_depth,
                            "sparse_depth": args.sparse_depth,
                            "temporal_channel": use_temporal,
                            "merge": "weighted RRF (k=60) + AHR-RAG-400 §6 boosts",
                        },
                    )

        report.config["corpus_snapshot"] = snapshot
        payload = report.to_dict()
        if args.output:
            Path(args.output).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return payload

    payload = asyncio.run(run())
    if args.output and "error" not in payload:
        # The per-question rows went to --output; stdout gets the summary so a
        # regression run stays readable in a terminal.
        summary = payload.get("summary", payload.get("summaries"))
        brief = (
            {
                "run_id": payload["run_id"],
                "summary": summary,
                **({"deltas": payload["deltas"]} if "deltas" in payload else {}),
                **({"decision": payload["decision"]} if "decision" in payload else {}),
            }
            if isinstance(summary, dict)
            else payload
        )
        print(json.dumps(brief, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _parse_weights(raw: str | None) -> dict[str, float] | None:
    """`dense=1.0,sparse=0.2,temporal=0.4` -> a weight table.

    Lets a sweep candidate be measured through the *full* pipeline, reranker
    included. The sweep alone cannot settle a weight change: it scores the fused
    order, and B4 established the cross-encoder rewrites that order.
    """
    if not raw:
        return None
    weights: dict[str, float] = {}
    for part in raw.split(","):
        name, _, value = part.partition("=")
        weights[name.strip()] = float(value)
    return weights


def _run_weight_sweep(
    golden: GoldenSet, args: argparse.Namespace, snapshot: dict[str, object]
) -> int:
    """Grid-search the fusion weights (AHR-RAG-400 §5).

    One embedding round trip per question, then the whole grid is scored over
    the cached channel outputs — the weights cannot change what the channels
    return, so re-retrieving per configuration would buy nothing.
    """
    from ahr.rag.embeddings import EmbeddingUnavailableError, build_client_from_env
    from ahr.rag.eval.sweep import capture_channels, sweep

    async def run() -> dict[str, object]:
        try:
            client = build_client_from_env()
        except EmbeddingUnavailableError as exc:
            return {"error": str(exc)}

        with psycopg.connect(get_settings().database_url) as connection:
            async with client:
                captures = await capture_channels(
                    golden,
                    connection,
                    client,
                    dense_depth=args.chunk_depth,
                    sparse_depth=args.sparse_depth,
                )

        payload = sweep(captures)
        payload["config"]["embedding_model"] = client.model_name
        payload["config"]["corpus_snapshot"] = snapshot
        if args.output:
            Path(args.output).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return payload

    payload = asyncio.run(run())
    if "error" in payload:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1

    # stdout gets the podium and the incumbent; the full grid goes to --output.
    raw_results = payload["results"]
    results: list[dict[str, Any]] = raw_results if isinstance(raw_results, list) else []
    config = payload.get("config")
    incumbent = next(
        (r for r in results if r["weights"] == {"dense": 1.0, "sparse": 0.6, "temporal": 0.15}),
        None,
    )
    print(
        json.dumps(
            {
                "run_id": payload["run_id"],
                "combinations": config.get("combinations") if isinstance(config, dict) else None,
                "top": results[:5],
                "incumbent": incumbent,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _run_query_type_sweep(golden: Any, args: argparse.Namespace) -> int:
    """Force each query_type per question and read the recall.

    B16 left one question open: the LLM planner classified far better and
    retrieved slightly worse, which is either a failure to transfer or a wrong
    yardstick. This produces the label defined by what the planner exists to
    serve, so the two can be told apart.
    """
    import asyncio

    from ahr.rag.embeddings import EmbeddingUnavailableError
    from ahr.rag.embeddings import build_client_from_env as build_embedder
    from ahr.rag.eval.query_type_sweep import run_sweep
    from ahr.rag.rerank import RerankUnavailableError
    from ahr.rag.rerank import build_client_from_env as build_reranker

    async def run() -> dict[str, Any]:
        try:
            client = build_embedder()
            reranker = build_reranker()
        except (EmbeddingUnavailableError, RerankUnavailableError) as exc:
            return {"error": str(exc)}

        async with client, reranker:
            with psycopg.connect(get_settings().database_url) as connection:
                return await run_sweep(
                    golden, connection=connection, client=client, reranker=reranker
                )

    payload = asyncio.run(run())
    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary = {k: v for k, v in payload.items() if k != "rows"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run_planner_diff(golden: Any, args: argparse.Namespace) -> int:
    """List where the two planners disagree, for a human to adjudicate.

    Neither planner can be scored until the golden set carries
    `expected_query_type`, and annotating ninety questions to find out is the
    expensive way round. Agreement is weak evidence both are right; the
    disagreements are the short list worth judging, and judging them *is* the
    annotation.
    """
    import asyncio

    from ahr.processing.llm import LlmUnavailableError
    from ahr.processing.llm import build_client_from_env as build_llm
    from ahr.rag.llm_planner import disagreements

    try:
        llm = build_llm()
    except LlmUnavailableError as exc:
        print(json.dumps({"error": f"llm unavailable: {exc}"}, ensure_ascii=False))
        return 1

    questions = [(q.id, q.question, q.asked_at) for q in golden.questions]

    async def run() -> list[dict[str, Any]]:
        async with llm:
            return await disagreements(llm, questions)

    rows = asyncio.run(run())
    payload = {
        "questions": len(questions),
        "disagreements": len(rows),
        "agreement_rate": round(1 - len(rows) / len(questions), 4) if questions else None,
        "rows": rows,
    }
    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_planner_eval(golden: Any, args: argparse.Namespace) -> int:
    """Score the planner, and refuse to look successful when nothing is annotated.

    `AHR-QSO-700` §8's planner accuracy has never had a number. Exiting 0 on an
    empty run would replace "unjudgeable" with "apparently fine", which is the
    worse of the two states — so an unannotated set is a non-zero exit that says
    what is missing.
    """
    from ahr.rag.eval.planner_accuracy import run_planner_eval

    payload = run_planner_eval(golden)
    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    for mistake in payload["mistakes"]:
        for note in mistake["notes"]:
            print(f"  {mistake['question_id']}  {note}")

    if payload["summary"]["overall"]["annotated"] == 0:
        print(
            "\n黄金集尚无 planner 标注"
            "（expected_query_type / expected_time / expected_entities）。\n"
            "AHR-QSO-700 §8 的 planner accuracy 因此仍然不可判定——不是失败，是没有量过。\n"
            "标注方法见 data/golden/README.md。",
            file=sys.stderr,
        )
        return 1
    return 0


def _run_generation_eval(
    golden: GoldenSet, args: argparse.Namespace, snapshot: dict[str, object]
) -> int:
    """Answer every golden question for real, then score the answers.

    Separate from the retrieval variants because it is a different kind of run:
    90 model round trips rather than 90 vector searches, and the metrics it
    produces — groundedness, citation precision, story coverage — are exactly
    the ones the retrieval evaluation is blind to.
    """
    from ahr.processing.llm import LlmUnavailableError
    from ahr.processing.llm import build_client_from_env as build_llm
    from ahr.rag.embeddings import EmbeddingUnavailableError
    from ahr.rag.embeddings import build_client_from_env as build_embedder
    from ahr.rag.eval.generation import run_generation_eval
    from ahr.rag.eval.latency import measure as measure_latency
    from ahr.rag.rerank import RerankUnavailableError
    from ahr.rag.rerank import build_client_from_env as build_reranker

    async def run() -> dict[str, object]:
        try:
            embedder = build_embedder()
            llm = build_llm()
        except (EmbeddingUnavailableError, LlmUnavailableError) as exc:
            return {"error": str(exc)}

        reranker = None
        try:
            reranker = build_reranker()
        except RerankUnavailableError as exc:
            print(f"warning: reranker unavailable, support scores will be null: {exc}")

        # The two runners take a differently typed `limit`, so they are called
        # separately rather than through one variable and a `**kwargs` bag. The
        # bag needed three `type: ignore`s to compile, and those ignores were
        # also hiding that `golden` had been annotated as `object`.
        async def measure(reranker_client: object) -> dict[str, object]:
            if args.variant == "latency":
                return await measure_latency(
                    golden,
                    embedder=embedder,
                    reranker=reranker_client,  # type: ignore[arg-type]
                    llm=llm,
                    limit=args.gen_limit or 24,
                )
            return await run_generation_eval(
                golden,
                embedder=embedder,
                reranker=reranker_client,  # type: ignore[arg-type]
                llm=llm,
                limit=args.gen_limit,
            )

        async with embedder, llm:
            if reranker is not None:
                async with reranker:
                    report = await measure(reranker)
            else:
                report = await measure(None)

        config = report.get("config")
        if isinstance(config, dict):
            config["corpus_snapshot"] = snapshot
        if args.output:
            Path(args.output).write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return report

    payload = asyncio.run(run())
    brief = (
        {"run_id": payload.get("run_id"), **payload["summary"]}  # type: ignore[dict-item]
        if args.output and "error" not in payload
        else payload
    )
    print(json.dumps(brief, indent=2, ensure_ascii=False))
    return 0


def cmd_seed_topics(args: argparse.Namespace) -> int:
    """Refresh the topic table from config/taxonomy.yaml.

    The enrichment pipeline seeds topics too, but editing a display name should
    not require re-running enrichment over the whole corpus.
    """
    from ahr.processing.topics import (
        load_content_type_display,
        load_display,
        load_taxonomy,
        load_vendors,
        seed_content_types,
        seed_topics,
        seed_vendors,
    )

    with psycopg.connect(get_settings().database_url) as connection:
        # All three dimensions of the topic map come from one file, so they are
        # refreshed together — seeding topics without the vendors that were
        # edited in the same commit would show half of an intended change.
        topics = seed_topics(connection, load_taxonomy(), load_display())
        vendors = seed_vendors(connection, load_vendors())
        content_types = seed_content_types(connection, load_content_type_display())
        connection.commit()
    print(
        json.dumps({"topics": topics, "vendors": vendors, "contentTypes": content_types}, indent=2)
    )
    return 0


def cmd_topic_quality(args: argparse.Namespace) -> int:
    """Freeze or evaluate the human-reviewed topic-map relation set."""
    from ahr.processing.topic_quality import (
        TopicQualityError,
        audit_corpus_bindings,
        build_dataset,
        build_review_packet,
        compare_review_packets,
        dump_dataset,
        evaluate_dataset,
        finalize_reviewed_dataset,
        load_dataset,
        load_review_packet,
    )

    try:
        if args.action == "sample":
            if not args.output:
                raise TopicQualityError("sample action requires --output")
            with psycopg.connect(get_settings().database_url) as connection:
                # The sampler runs one query per target/stratum while ingestion
                # continues in another service. Freeze a single MVCC view so
                # counts and examples cannot come from different corpus states.
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                payload = build_dataset(
                    connection,
                    per_stratum=args.per_stratum,
                    seed=args.seed,
                )
            dump_dataset(payload, args.output)
            summary = {
                "status": "sampled",
                "dataset_id": payload["dataset_id"],
                "samples": len(payload["samples"]),
                "output": args.output,
            }
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return 0

        dataset = load_dataset(args.golden)
        with psycopg.connect(get_settings().database_url) as connection:
            binding_audit = audit_corpus_bindings(connection, dataset)
        if args.action == "review-init":
            if not args.output or not args.reviewer:
                raise TopicQualityError("review-init requires --reviewer and --output")
            dump_dataset(build_review_packet(dataset, args.reviewer), args.output)
            print(
                json.dumps(
                    {
                        "status": "review_packet_created",
                        "dataset_id": dataset.dataset_id,
                        "reviewer": args.reviewer,
                        "samples": len(dataset.samples),
                        "corpus_binding": binding_audit,
                        "output": args.output,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        if args.action in {"review-compare", "labels-finalize"}:
            if not args.review_a or not args.review_b:
                raise TopicQualityError(f"{args.action} requires --review-a and --review-b")
            packet_a = load_review_packet(args.review_a, dataset)
            packet_b = load_review_packet(args.review_b, dataset)
            comparison = compare_review_packets(dataset, packet_a, packet_b)
            if args.action == "review-compare":
                if args.output:
                    dump_dataset(comparison, args.output)
                print(json.dumps(comparison, indent=2, ensure_ascii=False))
                return 2 if comparison["pending"] or comparison["disagreements"] else 0
            if not args.output or not args.labels_output:
                raise TopicQualityError("labels-finalize requires --output and --labels-output")
            adjudication = None
            if args.adjudication:
                try:
                    raw = yaml.safe_load(Path(args.adjudication).read_text(encoding="utf-8"))
                except (OSError, yaml.YAMLError) as exc:
                    raise TopicQualityError(
                        f"cannot read adjudication packet {args.adjudication}: {exc}"
                    ) from exc
                if not isinstance(raw, dict):
                    raise TopicQualityError("adjudication packet root must be an object")
                adjudication = raw
            full, labels = finalize_reviewed_dataset(dataset, packet_a, packet_b, adjudication)
            dump_dataset(full, args.output)
            dump_dataset(labels, args.labels_output)
            print(
                json.dumps(
                    {
                        "status": "finalized",
                        "dataset_id": dataset.dataset_id,
                        "samples": len(dataset.samples),
                        "agreement_rate": labels["agreement_rate"],
                        "disagreements": labels["disagreements"],
                        "output": args.output,
                        "labels_output": args.labels_output,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        report = evaluate_dataset(dataset)
        report["corpus_binding"] = binding_audit
        if args.output:
            Path(args.output).write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if args.action == "evaluate" and report["status"] != "ready":
            return 2
        return 0
    except TopicQualityError as exc:
        print(json.dumps({"status": "invalid", "detail": str(exc)}, ensure_ascii=False))
        return 1


def cmd_reasons(args: argparse.Namespace) -> int:
    from ahr.processing.llm import LlmUnavailableError, build_client_from_env
    from ahr.processing.recommendation import backfill_reasons

    async def run() -> dict[str, int]:
        try:
            client = build_client_from_env()
        except LlmUnavailableError as exc:
            return {"error": str(exc)}  # type: ignore[dict-item]
        async with client:
            with psycopg.connect(get_settings().database_url) as connection:
                return await backfill_reasons(
                    connection, limit=args.limit, client=client, force=args.force
                )

    print(json.dumps(asyncio.run(run()), indent=2, ensure_ascii=False))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from datetime import date, timedelta

    from ahr.processing.llm import LlmUnavailableError, build_client_from_env
    from ahr.processing.report import build_report, save_report

    period = args.period
    if args.date:
        key = args.date
    else:
        anchor = date.today() - timedelta(days=1)
        if period == "daily":
            key = anchor.isoformat()
        elif period == "weekly":
            iso = anchor.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        else:
            key = f"{anchor.year}-{anchor.month:02d}"

    async def run() -> dict[str, object]:
        client = None
        if not args.no_llm:
            try:
                client = build_client_from_env()
                await client.__aenter__()
            except LlmUnavailableError:
                client = None
        try:
            with psycopg.connect(get_settings().database_url) as connection:
                report = await build_report(connection, period, key, client=client)
                if report is None:
                    return {"period": period, "key": key, "status": "no_selected_items"}
                report_id = save_report(connection, report)
                if args.output:
                    Path(args.output).write_text(report.body_markdown, encoding="utf-8")
                return {
                    "period": period,
                    "key": key,
                    "report_id": str(report_id),
                    "items": len(report.items),
                    "model": report.model_name,
                    "summary": report.summary[:160],
                }
        finally:
            if client is not None:
                await client.__aexit__()

    print(json.dumps(asyncio.run(run()), indent=2, ensure_ascii=False))
    return 0


def cmd_publish_ready_reports(_args: argparse.Namespace) -> int:
    """Apply the deterministic publication gate to historical draft reports."""
    from ahr.processing.report import promote_stored_drafts

    with psycopg.connect(get_settings().database_url) as connection:
        result = promote_stored_drafts(connection)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_send_report(args: argparse.Namespace) -> int:
    """Send a stored daily report by email."""
    from ahr.processing.email import (
        EmailNotConfiguredError,
        SmtpConfig,
        already_delivered,
        build_message,
        delivery_key,
        record_delivery,
        report_delivery_allowed,
        send_message,
    )

    try:
        config = SmtpConfig.from_env()
    except EmailNotConfiguredError as exc:
        print(json.dumps({"status": "not_configured", "detail": str(exc)}, indent=2))
        return 1

    with psycopg.connect(get_settings().database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT title, summary, body_markdown, status FROM report"
                " WHERE period_type = 'daily' AND period_key = %s",
                (args.date,),
            )
            row = cursor.fetchone()

        if row is None:
            print(json.dumps({"status": "no_report", "date": args.date}, indent=2))
            return 1

        title, summary, body_markdown, report_status = row
        key = delivery_key(args.date, args.to)

        if already_delivered(connection, key) and not args.force:
            print(json.dumps({"status": "already_sent", "delivery_key": key[:16]}, indent=2))
            return 0

        if not report_delivery_allowed(report_status, dry_run=args.dry_run):
            print(
                json.dumps(
                    {
                        "status": "not_published",
                        "date": args.date,
                        "report_status": report_status,
                    },
                    indent=2,
                )
            )
            return 1

        if args.dry_run:
            print(
                json.dumps(
                    {
                        "status": "dry_run",
                        "to": args.to,
                        "subject": title,
                        "body_chars": len(body_markdown),
                        "report_status": report_status,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        message = build_message(
            config=config,
            recipient=args.to,
            title=title,
            summary=summary or "",
            body_markdown=body_markdown,
        )
        try:
            send_message(config, message)
        except Exception as exc:  # noqa: BLE001 - failure must be recorded, not raised
            record_delivery(
                connection,
                key=key,
                recipient=args.to,
                report_date=args.date,
                status="FAILED",
                error=str(exc),
            )
            print(json.dumps({"status": "failed", "error": str(exc)[:200]}, indent=2))
            return 1

        record_delivery(
            connection,
            key=key,
            recipient=args.to,
            report_date=args.date,
            status="SENT",
            error=None,
        )

    print(json.dumps({"status": "sent", "to": args.to, "date": args.date}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    # Without this the CLI emits nothing: configure_logging only ran inside the
    # FastAPI app, so a long scheduler run was completely unobservable.
    configure_logging(get_settings().service_name)

    parser = argparse.ArgumentParser(prog="ahr")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync-sources", help="load config/sources.yaml into PostgreSQL")
    sync.add_argument("--path", default=DEFAULT_SOURCES_PATH)
    sync.add_argument("--config-version", default="2026-08-01.1")
    sync.set_defaults(func=cmd_sync_sources)

    probe = sub.add_parser("probe", help="run discovery and fulltext against real sources")
    probe.add_argument("--limit", type=int, default=10)
    probe.add_argument("--profile", default=None)
    probe.add_argument("--output", default=None)
    probe.set_defaults(func=cmd_probe)

    ingest = sub.add_parser("ingest", help="fetch, extract and persist content to PostgreSQL")
    ingest.add_argument("--limit", type=int, default=200)
    ingest.add_argument("--profile", default=None)
    ingest.add_argument("--source", default=None)
    ingest.add_argument("--max-documents", type=int, default=10)
    ingest.add_argument("--output", default=None)
    ingest.set_defaults(func=cmd_ingest)

    process = sub.add_parser("process", help="chunk, de-duplicate and enrich stored content")
    process.add_argument("--limit", type=int, default=50)
    process.add_argument("--no-enrich", action="store_true", help="chunk and dedup only")
    process.set_defaults(func=cmd_process)

    schedule = sub.add_parser("schedule", help="run the ingestion scheduler")
    schedule.add_argument("--once", action="store_true", help="run a single tick and exit")
    schedule.add_argument("--interval", type=int, default=60)
    schedule.add_argument("--batch-size", type=int, default=20)
    schedule.add_argument("--max-documents", type=int, default=5)
    schedule.set_defaults(func=cmd_schedule)

    select = sub.add_parser("select", help="rank recent content into the daily shortlist")
    select.add_argument("--days", type=int, default=7)
    select.set_defaults(func=cmd_select)

    usage = sub.add_parser("usage", help="report recorded LLM token usage")
    usage.add_argument("--days", type=int, default=30)
    usage.set_defaults(func=cmd_usage)

    support = sub.add_parser(
        "backfill-support", help="score citations that predate support scoring"
    )
    support.add_argument("--limit", type=int, default=200)
    support.set_defaults(func=cmd_backfill_support)

    heat = sub.add_parser("heat", help="recompute hot_score for recent content")
    heat.add_argument("--days", type=int, default=7)
    heat.set_defaults(func=cmd_heat)

    clusters = sub.add_parser("cluster", help="group content into event Stories")
    clusters.add_argument("--days", type=int, default=14)
    clusters.set_defaults(func=cmd_cluster)

    pipeline = sub.add_parser(
        "pipeline",
        help="run everything after ingestion: process, cluster, select, reasons, reports",
    )
    pipeline.add_argument("--interval", type=int, default=900)
    pipeline.add_argument("--process-limit", type=int, default=60)
    pipeline.add_argument("--reason-limit", type=int, default=40)
    pipeline.add_argument("--no-reports", action="store_true", help="skip report generation")
    pipeline.add_argument("--once", action="store_true", help="single pass then exit")
    pipeline.set_defaults(func=cmd_pipeline)

    fix_titles = sub.add_parser("fix-titles", help="re-sanitise titles already in the database")
    fix_titles.add_argument("--dry-run", action="store_true")
    fix_titles.set_defaults(func=cmd_fix_titles)

    rechunk = sub.add_parser(
        "rechunk", help="re-split current revisions with the current chunking rules"
    )
    rechunk.add_argument(
        "--oversized-only",
        action="store_true",
        help="only rebuild current revisions containing a chunk above the hard token cap",
    )
    rechunk.set_defaults(func=cmd_rechunk)

    embed = sub.add_parser("embed", help="generate embeddings for content chunks")
    embed.add_argument("--limit", type=int, default=500)
    embed.add_argument("--batch-size", type=int, default=64)
    embed.set_defaults(func=cmd_embed)

    rag_eval = sub.add_parser("rag-eval", help="score retrieval against the golden set")
    rag_eval.add_argument("--golden", default="/app/data/golden")
    rag_eval.add_argument(
        "--variant",
        choices=[
            "b1",
            "b2-sparse",
            "b2-union",
            "b3-rrf",
            "b3-no-temporal",
            "b4-rerank",
            "b7-temporal-fit",
            "b9-dimensions",
            "sweep",
            "generation",
            "latency",
            "planner",
            "planner-diff",
            "query-type-sweep",
            "specialist-ab",
        ],
        default="b1",
        help=(
            "b1 dense only, b2-sparse keyword only, b2-union both interleaved, "
            "b3-rrf weighted RRF over dense+sparse+temporal, "
            "b3-no-temporal the same without the time channel, "
            "b4-rerank b3 reordered by the cross-encoder, "
            "b7-temporal-fit b4 plus a recency blend for time-scoped queries, "
            "b9-dimensions b7 plus §6 directness and source_fit, "
            "sweep grid-search the fusion weights on Recall@40 (AHR-RAG-400 §5), "
            "generation end-to-end answers scored for groundedness and citations, "
            "latency per-stage p50/p95 (AHR-RAG-400 §14), "
            "planner query_type/time/entity accuracy against the golden set "
            "(AHR-QSO-700 §8; needs no provider or database), "
            "planner-diff where the regex and LLM planners disagree, "
            "query-type-sweep which query_type actually retrieves best per question, "
            "specialist-ab one-snapshot entity/noise rerank A/B for an annotated specialist set"
        ),
    )
    rag_eval.add_argument(
        "--gen-limit", type=int, default=None, help="score only the first N questions"
    )
    rag_eval.add_argument("--rerank-top-n", type=int, default=24, help="AHR-RAG-400 §6")
    rag_eval.add_argument(
        "--rerank-candidates",
        type=int,
        default=100,
        help="how many fused candidates the cross-encoder scores (latency driver)",
    )
    rag_eval.add_argument(
        "--weights",
        default=None,
        help="override fusion weights, e.g. dense=1.0,sparse=0.2,temporal=0.4",
    )
    rag_eval.add_argument("--chunk-depth", type=int, default=60, help="AHR-RAG-400 §5 topK")
    rag_eval.add_argument("--sparse-depth", type=int, default=40, help="AHR-RAG-400 §5 FTS topK")
    rag_eval.add_argument("--output", default=None, help="write the full per-question report here")
    rag_eval.add_argument(
        "--question-id",
        default=None,
        help="replay one golden question by id before running the whole set",
    )
    rag_eval.add_argument(
        "--llm-planner",
        action="store_true",
        help="plan with the model instead of the regexes (AHR-QSO-700 §8 planner accuracy)",
    )
    rag_eval.add_argument("--validate", action="store_true", help="check the set, do not retrieve")
    rag_eval.add_argument(
        "--skip-unusable",
        action="store_true",
        help="exclude questions whose annotated items are missing or unchunked",
    )
    rag_eval.add_argument(
        "--allow-partial",
        action="store_true",
        help="skip the 15-per-category check (fixtures only)",
    )
    rag_eval.set_defaults(func=cmd_rag_eval)

    seed = sub.add_parser("seed-topics", help="refresh topic names and grouping from taxonomy")
    seed.set_defaults(func=cmd_seed_topics)

    topic_quality = sub.add_parser(
        "topic-quality",
        help="sample, validate or evaluate human-reviewed topic-map relations",
    )
    topic_quality.add_argument(
        "action",
        choices=[
            "sample",
            "validate",
            "review-init",
            "review-compare",
            "labels-finalize",
            "evaluate",
        ],
    )
    topic_quality.add_argument(
        "--golden",
        default="/app/data/topic-map-review/annotations.yaml",
        help="frozen YAML dataset used by validate/evaluate",
    )
    topic_quality.add_argument("--output", default=None)
    topic_quality.add_argument("--labels-output", default=None)
    topic_quality.add_argument("--reviewer", default=None)
    topic_quality.add_argument("--review-a", default=None)
    topic_quality.add_argument("--review-b", default=None)
    topic_quality.add_argument("--adjudication", default=None)
    topic_quality.add_argument("--per-stratum", type=int, default=20)
    topic_quality.add_argument("--seed", default="topic-map-golden-v1")
    topic_quality.set_defaults(func=cmd_topic_quality)

    reasons = sub.add_parser("reasons", help="write LLM recommendation reasons for selections")
    reasons.add_argument("--limit", type=int, default=40)
    reasons.add_argument("--force", action="store_true", help="rewrite even if already generated")
    reasons.set_defaults(func=cmd_reasons)

    report = sub.add_parser("report", help="generate a daily/weekly/monthly report")
    report.add_argument("--period", choices=["daily", "weekly", "monthly"], default="daily")
    report.add_argument("--date", default=None, help="YYYY-MM-DD / YYYY-Www / YYYY-MM")
    report.add_argument("--no-llm", action="store_true", help="skip the narrative summary")
    report.add_argument("--output", default=None, help="also write the markdown here")
    report.set_defaults(func=cmd_report)

    publish_ready = sub.add_parser(
        "publish-ready-reports",
        help="evaluate historical draft reports with the non-blocking publication gate",
    )
    publish_ready.set_defaults(func=cmd_publish_ready_reports)

    send = sub.add_parser("send-report", help="email a stored daily report")
    send.add_argument("--date", required=True, help="YYYY-MM-DD")
    send.add_argument("--to", required=True, help="recipient address")
    send.add_argument("--dry-run", action="store_true", help="render without sending")
    send.add_argument("--force", action="store_true", help="resend even if already delivered")
    send.set_defaults(func=cmd_send_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

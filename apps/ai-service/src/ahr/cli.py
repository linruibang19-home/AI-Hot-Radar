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
from pathlib import Path

import psycopg

from ahr.config import get_settings
from ahr.ingestion.registry import load_sources, summarize, sync_sources
from ahr.observability import configure_logging

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
    from ahr.processing.pipeline import chunk_revision

    before = 0
    after = 0
    revisions = 0

    with psycopg.connect(get_settings().database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT cr.id, cr.body_text
                  FROM content_revision cr
                  JOIN content_item ci ON ci.current_revision_id = cr.id
                 WHERE cr.body_text IS NOT NULL AND length(cr.body_text) > 0
                 ORDER BY cr.created_at
                """
            )
            rows = cursor.fetchall()

        for revision_id, body in rows:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM content_chunk WHERE content_revision_id = %s",
                    (revision_id,),
                )
                before += cursor.fetchone()[0]

            written = chunk_revision(connection, revision_id, body)
            after += written
            revisions += 1

        connection.commit()

    print(
        json.dumps(
            {"revisions": revisions, "chunks_before": before, "chunks_after": after},
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


def cmd_seed_topics(args: argparse.Namespace) -> int:
    """Refresh the topic table from config/taxonomy.yaml.

    The enrichment pipeline seeds topics too, but editing a display name should
    not require re-running enrichment over the whole corpus.
    """
    from ahr.processing.topics import load_display, load_taxonomy, seed_topics

    with psycopg.connect(get_settings().database_url) as connection:
        written = seed_topics(connection, load_taxonomy(), load_display())
        connection.commit()
    print(json.dumps({"topics": written}, indent=2))
    return 0


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


def cmd_send_report(args: argparse.Namespace) -> int:
    """Send a stored daily report by email."""
    from ahr.processing.email import (
        EmailNotConfiguredError,
        SmtpConfig,
        already_delivered,
        build_message,
        delivery_key,
        record_delivery,
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
                "SELECT title, summary, body_markdown FROM report"
                " WHERE period_type = 'daily' AND period_key = %s",
                (args.date,),
            )
            row = cursor.fetchone()

        if row is None:
            print(json.dumps({"status": "no_report", "date": args.date}, indent=2))
            return 1

        title, summary, body_markdown = row
        key = delivery_key(args.date, args.to)

        if already_delivered(connection, key) and not args.force:
            print(json.dumps({"status": "already_sent", "delivery_key": key[:16]}, indent=2))
            return 0

        if args.dry_run:
            print(
                json.dumps(
                    {
                        "status": "dry_run",
                        "to": args.to,
                        "subject": title,
                        "body_chars": len(body_markdown),
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

    rechunk = sub.add_parser("rechunk", help="re-split every stored revision with current rules")
    rechunk.set_defaults(func=cmd_rechunk)

    embed = sub.add_parser("embed", help="generate embeddings for content chunks")
    embed.add_argument("--limit", type=int, default=500)
    embed.add_argument("--batch-size", type=int, default=64)
    embed.set_defaults(func=cmd_embed)

    seed = sub.add_parser("seed-topics", help="refresh topic names and grouping from taxonomy")
    seed.set_defaults(func=cmd_seed_topics)

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

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


def cmd_report(args: argparse.Namespace) -> int:
    from datetime import date, timedelta

    from ahr.processing.llm import LlmUnavailableError, build_client_from_env
    from ahr.processing.report import build_daily_report, save_report

    target = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

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
                report = await build_daily_report(connection, target, client=client)
                if report is None:
                    return {"date": target.isoformat(), "status": "no_selected_items"}
                report_id = save_report(connection, report)
                if args.output:
                    Path(args.output).write_text(report.body_markdown, encoding="utf-8")
                return {
                    "date": target.isoformat(),
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


def main(argv: list[str] | None = None) -> int:
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

    report = sub.add_parser("report", help="generate the daily report from the shortlist")
    report.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to yesterday")
    report.add_argument("--no-llm", action="store_true", help="skip the narrative summary")
    report.add_argument("--output", default=None, help="also write the markdown here")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

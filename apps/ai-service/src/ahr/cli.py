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

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

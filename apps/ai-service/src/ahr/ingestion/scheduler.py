"""Ingestion scheduler.

Polls sources on their own cadence so the pipeline runs unattended, which is
what AHR-ROADMAP-800's "30 real sources running continuously for 24h" acceptance
requires.

Two safeguards matter here:

* `next_poll_at` is claimed with `FOR UPDATE SKIP LOCKED`, so running several
  workers never double-polls a source (AHR-INGEST-1000 §2).
* A failing source backs off exponentially instead of being retried every tick,
  so one broken host cannot dominate the schedule.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from ahr.config import get_settings
from ahr.ingestion.http import HttpConfig, HttpFetcher
from ahr.ingestion.models import SourceConfig
from ahr.ingestion.pipeline import ingest_source

logger = logging.getLogger(__name__)

# Priority drives cadence: P0 sources are the ones the product promises to be
# fresh about (AHR-KPI-007 targets p95 <= 20 minutes for P0 RSS).
POLL_INTERVALS = {"P0": 900, "P1": 3600, "P2": 10800}

MAX_BACKOFF_SECONDS = 6 * 3600


@dataclass
class TickResult:
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    persisted: int = 0


def _claim_due_sources(connection: Any, limit: int) -> list[SourceConfig]:
    """Atomically claim sources whose next_poll_at has passed.

    SKIP LOCKED lets additional workers claim different rows instead of
    blocking, and the immediate next_poll_at bump means a crashed worker's
    source simply becomes due again rather than being lost.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH due AS (
                SELECT id FROM source
                 WHERE configured_enabled
                   AND runtime_state <> 'DISABLED'
                   AND (next_poll_at IS NULL OR next_poll_at <= now())
                 ORDER BY priority, next_poll_at NULLS FIRST
                 LIMIT %s
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE source s
               SET next_poll_at = now() + (%s || ' seconds')::interval
              FROM due
             WHERE s.id = due.id
         RETURNING s.id, s.name, s.organization, s.profile, s.source_tier, s.priority,
                   s.content_access, s.verification, s.configured_enabled, s.discovery_url,
                   s.repository, s.subject, s.homepage_url, s.region, s.source_group
            """,
            (limit, POLL_INTERVALS["P2"]),
        )
        rows = cursor.fetchall()
    connection.commit()

    return [
        SourceConfig(
            id=r[0],
            name=r[1],
            organization=r[2],
            profile=r[3],
            tier=r[4],
            priority=r[5],
            content_access=r[6],
            verification=r[7],
            enabled=r[8],
            discovery_url=r[9],
            repository=r[10],
            subject=r[11],
            homepage_url=r[12],
            region=r[13],
            group=r[14],
        )
        for r in rows
    ]


def _reschedule(connection: Any, source: SourceConfig, *, failures: int) -> None:
    """Set the next poll time, backing off after repeated failures."""
    base = POLL_INTERVALS.get(source.priority, POLL_INTERVALS["P2"])
    if failures:
        base = min(base * (2**failures), MAX_BACKOFF_SECONDS)
    # Jitter prevents every source added in the same sweep from polling in lockstep.
    delay = int(base * random.uniform(0.85, 1.15))

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE source SET next_poll_at = now() + (%s || ' seconds')::interval WHERE id = %s",
            (delay, source.id),
        )
    connection.commit()


def _failure_count(connection: Any, source_id: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT consecutive_failures FROM source WHERE id = %s", (source_id,))
        row = cursor.fetchone()
    return int(row[0]) if row and row[0] else 0


async def run_tick(*, batch_size: int = 20, max_documents: int = 5) -> TickResult:
    """Poll every source that is currently due."""
    result = TickResult()
    token = os.environ.get("GITHUB_TOKEN") or None

    with psycopg.connect(get_settings().database_url) as connection:
        sources = _claim_due_sources(connection, batch_size)
        result.claimed = len(sources)
        if not sources:
            return result

        async with HttpFetcher(HttpConfig()) as fetcher:
            for source in sources:
                try:
                    outcome = await ingest_source(
                        source, fetcher, connection, token=token, max_documents=max_documents
                    )
                    result.persisted += outcome.persisted
                    if outcome.state in ("ACTIVE", "METADATA_ONLY"):
                        result.succeeded += 1
                    else:
                        result.failed += 1
                except Exception as exc:  # noqa: BLE001 - one source must not stop the tick
                    connection.rollback()
                    result.failed += 1
                    logger.warning("source %s failed: %s", source.id, exc)

                _reschedule(connection, source, failures=_failure_count(connection, source.id))
                await asyncio.sleep(0.2)

    return result


async def run_forever(
    *, interval_seconds: int = 60, batch_size: int = 20, max_documents: int = 5
) -> None:
    """Run ticks until cancelled."""
    logger.info("scheduler started: interval=%ss batch=%s", interval_seconds, batch_size)
    while True:
        try:
            result = await run_tick(batch_size=batch_size, max_documents=max_documents)
            if result.claimed:
                logger.info(
                    "tick claimed=%s ok=%s failed=%s persisted=%s",
                    result.claimed,
                    result.succeeded,
                    result.failed,
                    result.persisted,
                )
        except Exception as exc:  # noqa: BLE001 - the loop must survive any single tick
            logger.exception("scheduler tick failed: %s", exc)
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(interval_seconds)


def seed_poll_schedule(connection: Any) -> int:
    """Give every enabled source an initial next_poll_at, staggered.

    Without this the first tick would claim only `batch_size` sources and leave
    the rest with NULL, which orders unpredictably.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE source
               SET next_poll_at = now() + ((random() * 600) || ' seconds')::interval
             WHERE configured_enabled AND next_poll_at IS NULL
            """
        )
        count = cursor.rowcount
    connection.commit()
    return int(count)


def schedule_summary(connection: Any) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FILTER (WHERE next_poll_at IS NOT NULL),
                   count(*) FILTER (WHERE next_poll_at <= now()),
                   min(next_poll_at), max(next_poll_at)
              FROM source WHERE configured_enabled
            """
        )
        row = cursor.fetchone()

    now = datetime.now(UTC)
    return {
        "scheduled": int(row[0] or 0),
        "due_now": int(row[1] or 0),
        "next_due_in_seconds": int((row[2] - now).total_seconds()) if row[2] else None,
        "furthest_due_in_seconds": int((row[3] - now).total_seconds()) if row[3] else None,
    }

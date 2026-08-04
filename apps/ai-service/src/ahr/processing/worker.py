"""Downstream pipeline worker.

Ingestion has run continuously since M1, but everything after it — enrichment,
selection, clustering, recommendation reasons, reports — only ever ran when
someone typed a CLI command. The result was a site that kept collecting content
and stopped showing it: 141 items sat in PENDING, and 精选 / 热点 / 事件聚合 /
日报 were all frozen at whenever the last manual run happened.

This closes that loop. The stages run in dependency order, because each one
consumes what the previous produced:

    process   raw rows        -> zh_title, summary, entities, topics, quality
    embed     new chunks      -> vectors for retrieval (M4)
    cluster   enriched items  -> stories, independent_source_count, hot_score
    select    scored items    -> the daily shortlist (needs corroboration counts)
    reasons   selections      -> LLM recommendation text
    report    selections      -> daily / weekly / monthly digests

Clustering deliberately precedes selection: `select-v2` reads
`story.independent_source_count`, so running it first would score every item as
uncorroborated and undo the M3 fix.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from ahr.config import get_settings
from ahr.rag.planner import DISPLAY_TIMEZONE

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "pipeline-v1"

# Postgres advisory lock key. A pass can outlast its interval — enrichment of a
# large backlog takes minutes — and two overlapping passes would double-charge
# the LLM for the same items and race on selection_record.
ADVISORY_LOCK_KEY = 0x41485231  # "AHR1"


@dataclass
class PipelineResult:
    started_at: str
    duration_seconds: float = 0.0
    stages: dict[str, Any] = field(default_factory=dict)
    skipped: str | None = None


def _try_lock(connection: Any) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        return bool(cursor.fetchone()[0])


def _unlock(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))


# A daily digest of a day that is still running is a digest of half a day. The
# pipeline passes every 15 minutes, so today's report was being rewritten all
# day on whatever had arrived so far — at noon it summarised a morning and
# called it the day. Nothing is published for today until this hour, local time.
DAILY_CUTOFF_HOUR = 21


def _period_keys(now: datetime) -> list[tuple[str, str]]:
    """Which report periods to keep current, given the local wall clock.

    Yesterday, the current week and the current month are always refreshed:
    yesterday settles to its final form as the last of its items finish
    processing, and a week or a month in progress is legitimately a running
    total in a way a single day is not.

    Today's daily appears only after `DAILY_CUTOFF_HOUR`. Before that the site
    shows yesterday's, which is complete, rather than a partial one that
    contradicts itself every quarter of an hour.
    """
    local = now.astimezone(DISPLAY_TIMEZONE)
    today = local.date()
    yesterday = today - timedelta(days=1)
    iso = today.isocalendar()

    keys: list[tuple[str, str]] = []
    if local.hour >= DAILY_CUTOFF_HOUR:
        keys.append(("daily", today.isoformat()))
    keys.extend(
        [
            ("daily", yesterday.isoformat()),
            ("weekly", f"{iso.year}-W{iso.week:02d}"),
            ("monthly", f"{today.year}-{today.month:02d}"),
        ]
    )
    return keys


def _report_is_stale(connection: Any, period: str, key: str) -> bool:
    """Regenerate only when there is new material.

    Reports cost an LLM call each, so a fixed interval would spend money
    rewriting an identical digest. Comparing against the newest selection in the
    period means a quiet hour costs nothing.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT generated_at FROM report WHERE period_type = %s AND period_key = %s",
            (period, key),
        )
        row = cursor.fetchone()
        if row is None:
            return True
        generated_at = row[0]

        # selection_record has no updated_at, so a reason rewritten in place
        # would not move this timestamp. That is the right behaviour here: the
        # report lists selections, and rewording a card's reason does not change
        # which items the digest covers.
        cursor.execute("SELECT max(created_at) FROM selection_record WHERE withdrawn_at IS NULL")
        newest = cursor.fetchone()[0]

    if newest is None:
        return False
    return bool(newest > generated_at)


async def run_once(
    *,
    process_limit: int = 60,
    reason_limit: int = 40,
    cluster_days: int = 30,
    select_days: int = 7,
    embed_limit: int = 400,
    with_reports: bool = True,
) -> PipelineResult:
    """Run one full downstream pass. Safe to call concurrently; extra callers no-op."""
    from ahr.processing.heat import rescore
    from ahr.processing.llm import LlmUnavailableError, build_client_from_env
    from ahr.processing.pipeline import process_pending
    from ahr.processing.recommendation import backfill_reasons
    from ahr.processing.report import build_report, save_report
    from ahr.processing.selection import select_for_days
    from ahr.processing.story_repository import recluster, sync_item_heat
    from ahr.rag.backfill import backfill_embeddings
    from ahr.rag.embeddings import EmbeddingUnavailableError
    from ahr.rag.embeddings import build_client_from_env as build_embedding_client

    started = datetime.now(UTC)
    result = PipelineResult(started_at=started.isoformat())
    began = time.monotonic()

    with psycopg.connect(get_settings().database_url) as guard:
        if not _try_lock(guard):
            logger.info("pipeline skipped: another pass holds the lock")
            result.skipped = "another pass is already running"
            return result

        try:
            client = None
            try:
                client = build_client_from_env()
                await client.__aenter__()
            except LlmUnavailableError as exc:
                # Enrichment and reasons need the model, but clustering,
                # selection and heat do not. A provider outage must degrade the
                # site, not stop it updating.
                logger.warning("pipeline: LLM unavailable, running non-LLM stages only: %s", exc)

            try:
                if client is not None:
                    stats = await process_pending(limit=process_limit, client=client)
                    # ProcessStats is a dataclass; the result is logged as JSON.
                    result.stages["process"] = asdict(stats)

                # Embedding is independent of the LLM provider, so it runs even
                # when DeepSeek is down. Without it in the loop the vector index
                # only covers whatever existed at the last manual backfill, and
                # the newest content — the reason anyone searches — is missing.
                try:
                    embed_client = build_embedding_client()
                except EmbeddingUnavailableError as exc:
                    logger.warning("pipeline: embeddings unavailable: %s", exc)
                else:
                    async with embed_client:
                        with psycopg.connect(get_settings().database_url) as connection:
                            result.stages["embed"] = await backfill_embeddings(
                                connection, client=embed_client, limit=embed_limit
                            )

                with psycopg.connect(get_settings().database_url) as connection:
                    result.stages["cluster"] = recluster(connection, days=cluster_days)
                    result.stages["heat"] = rescore(connection, days=cluster_days)
                    result.stages["heat_sync"] = sync_item_heat(connection)
                    connection.commit()

                    result.stages["select"] = select_for_days(connection, days=select_days)

                if client is not None:
                    with psycopg.connect(get_settings().database_url) as connection:
                        result.stages["reasons"] = await backfill_reasons(
                            connection, limit=reason_limit, client=client
                        )

                if with_reports:
                    result.stages["reports"] = await _refresh_reports(
                        client, build_report, save_report
                    )
            finally:
                if client is not None:
                    await client.__aexit__(None, None, None)
        finally:
            _unlock(guard)

    result.duration_seconds = round(time.monotonic() - began, 2)
    process = result.stages.get("process") or {}
    embed = result.stages.get("embed") or {}
    cluster = result.stages.get("cluster") or {}
    select = result.stages.get("select") or {}
    logger.info(
        "pipeline pass done in %ss: enriched=%s embedded=%s stories=%s multi_source=%s "
        "selected=%s reports=%s",
        result.duration_seconds,
        process.get("enriched", 0),
        embed.get("embedded", 0),
        cluster.get("stories", 0),
        cluster.get("multi_source_stories", 0),
        select.get("selected", 0),
        result.stages.get("reports", {}),
    )
    return result


async def _refresh_reports(client: Any, build_report: Any, save_report: Any) -> dict[str, str]:
    # Keyed by "period:key", not period: the daily entry appears twice (today
    # and yesterday) and one would otherwise overwrite the other's status.
    written: dict[str, str] = {}
    # The wall clock in the display timezone, not UTC. `datetime.now(UTC).date()`
    # is the previous day for the whole Beijing morning, so before 08:00 the
    # worker refreshed the wrong day's digest.
    for period, key in _period_keys(datetime.now(UTC)):
        label = f"{period}:{key}"
        with psycopg.connect(get_settings().database_url) as connection:
            if not _report_is_stale(connection, period, key):
                written[label] = "unchanged"
                continue

            report = await build_report(connection, period, key, client=client)
            if report is None:
                written[label] = "no_selected_items"
                continue
            save_report(connection, report)
            connection.commit()
            written[label] = "written"

    return written


async def run_forever(
    *,
    interval_seconds: int,
    process_limit: int,
    reason_limit: int,
    with_reports: bool = True,
) -> None:
    """Loop until cancelled.

    A failing pass logs and waits rather than exiting: the container restart
    policy would otherwise turn one bad row into a crash loop that also stops
    the stages that were working.
    """
    # Announce startup. A pass takes minutes, and without this the container
    # produced no output at all until the first one finished — indistinguishable
    # from a worker that had failed to start.
    logger.info(
        "pipeline worker started: interval=%ss process_limit=%s reason_limit=%s reports=%s (%s)",
        interval_seconds,
        process_limit,
        reason_limit,
        with_reports,
        PIPELINE_VERSION,
    )

    while True:
        try:
            await run_once(
                process_limit=process_limit,
                reason_limit=reason_limit,
                with_reports=with_reports,
            )
        except Exception:  # noqa: BLE001 - a worker loop must not die
            logger.exception("pipeline pass failed; retrying after the interval")

        await asyncio.sleep(interval_seconds)

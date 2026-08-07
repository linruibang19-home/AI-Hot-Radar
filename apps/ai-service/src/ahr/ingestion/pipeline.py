"""Ingestion pipeline.

Runs the loop from AHR-INGEST-1000 §1 for one source:

    discover -> (fetch article when needed) -> extract -> gate -> persist

and advances the cursor only after everything commits.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import psycopg

from ahr.config import get_settings
from ahr.ingestion.adapters.arxiv import ArxivPaperAdapter
from ahr.ingestion.adapters.changelog import DocsChangelogAdapter
from ahr.ingestion.adapters.github_releases import GitHubReleasesAdapter
from ahr.ingestion.adapters.github_repo import GitHubRepoActivityAdapter
from ahr.ingestion.adapters.listing import HtmlListingAdapter
from ahr.ingestion.adapters.public_api import PublicJsonApiAdapter
from ahr.ingestion.adapters.rss import RssAtomAdapter
from ahr.ingestion.article import extract_article
from ahr.ingestion.errors import IngestionError
from ahr.ingestion.fulltext_gate import ExtractedDocument, evaluate
from ahr.ingestion.http import HttpConfig, HttpFetcher
from ahr.ingestion.models import SourceConfig
from ahr.ingestion.repository import (
    PersistStats,
    finish_crawl_run,
    load_cursor,
    persist_document,
    record_source_failure,
    save_cursor,
    start_crawl_run,
    update_source_state,
)

# How many documents to pull per source per run. Keeps a first sweep bounded
# while still satisfying the "latest 3" activation gate many times over.
DEFAULT_MAX_DOCUMENTS = 10


@dataclass
class SourceResult:
    source_id: str
    profile: str
    state: str
    discovered: int = 0
    persisted: int = 0
    fulltext: int = 0
    metadata_only: int = 0
    rejected: int = 0
    errors: list[str] = field(default_factory=list)
    error_code: str | None = None


def build_adapter(source: SourceConfig, fetcher: HttpFetcher, token: str | None) -> Any:
    """Map a profile to its adapter. Returns None when unsupported."""
    match source.profile:
        case "github_release_api":
            return GitHubReleasesAdapter(fetcher, token=token, page_limit=1)
        case "github_repo_activity":
            return GitHubRepoActivityAdapter(fetcher, token=token)
        case "arxiv_feed_paper":
            return ArxivPaperAdapter(fetcher)
        case "rss_to_article" | "author_feed_to_article":
            return RssAtomAdapter(fetcher)
        case "docs_changelog":
            return DocsChangelogAdapter(fetcher)
        case "static_listing_to_article" | "dynamic_listing_to_article":
            return HtmlListingAdapter(fetcher)
        case "public_json_api":
            return PublicJsonApiAdapter(fetcher)
        case _:
            return None


def _state_from_evidence(connection: Any, source_id: str) -> str | None:
    """Re-derive a source's verdict from stored fulltext attempts.

    Reading `runtime_state` back would let one bad run pin a healthy source in a
    wrong state forever. The activation gate (AHR-SOURCE-900 §5) is about
    observed documents, so ask the evidence table instead.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FILTER (WHERE decision = 'ACCEPTED'),
                   count(*) FILTER (WHERE decision = 'METADATA_ONLY')
              FROM fulltext_attempt
             WHERE source_id = %s
            """,
            (source_id,),
        )
        row = cursor.fetchone()

    if not row:
        return None
    accepted, metadata_only = int(row[0] or 0), int(row[1] or 0)
    if accepted >= 2:
        return "ACTIVE"
    if metadata_only:
        return "METADATA_ONLY"
    return None


async def ingest_source(
    source: SourceConfig,
    fetcher: HttpFetcher,
    connection: Any,
    *,
    token: str | None = None,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
) -> SourceResult:
    result = SourceResult(source_id=source.id, profile=source.profile, state="PROBING")

    adapter = build_adapter(source, fetcher, token)
    if adapter is None:
        result.state = "UNSUPPORTED_PROFILE"
        return result

    cursor_state = load_cursor(connection, source.id)
    run_id = start_crawl_run(connection, source.id)
    connection.commit()

    stats = PersistStats()
    try:
        batch = await adapter.discover(source, cursor_state)
    except IngestionError as exc:
        result.error_code = exc.code
        result.errors.append(str(exc)[:160])
        finish_crawl_run(
            connection,
            run_id,
            status="FAILED",
            stats=stats,
            discovered=0,
            error_code=exc.code,
            error_detail=str(exc),
        )
        # The ladder in AHR-SOURCE-900 §5 decides the verdict. Quarantining here
        # on the first error — which is what this used to do — meant a single
        # DNS blip sidelined eighteen working first-party sources at once.
        result.state = record_source_failure(
            connection,
            source.id,
            error_code=exc.code,
            error_detail=str(exc),
            retryable=exc.retryable,
        )
        connection.commit()
        return result

    result.discovered = len(batch.items)

    for item in batch.items[:max_documents]:
        try:
            if item.requires_fetch:
                response = await fetcher.fetch(item.candidate_url)
                extraction = extract_article(
                    response,
                    source_id=source.id,
                    title_hint=item.title_hint,
                    published_hint=item.published_at_hint,
                )
                document = extraction.document
                gate = evaluate(document, is_release=source.is_release_like)
                persist_document(
                    connection,
                    source=source,
                    item=item,
                    body_text=document.body_text,
                    body_markdown=extraction.body_markdown,
                    gate=gate,
                    run_id=run_id,
                    raw_body=response.body,
                    http_status=response.status_code,
                    response_headers=response.headers,
                    final_url=response.final_url,
                    extractor=document.extractor,
                    stats=stats,
                )
            else:
                body = item.body_markdown or ""
                document = ExtractedDocument(
                    body_text=body,
                    title=item.title_hint,
                    canonical_url=item.candidate_url,
                    published_at=item.published_at_hint,
                    source_id=source.id,
                    extractor="api_body",
                )
                gate = evaluate(document, is_release=True)
                persist_document(
                    connection,
                    source=source,
                    item=item,
                    body_text=body,
                    body_markdown=body,
                    gate=gate,
                    run_id=run_id,
                    http_status=batch.http_status,
                    extractor="api_body",
                    stats=stats,
                )
            # Commit per document so one bad page cannot roll back a whole run.
            connection.commit()
        except IngestionError as exc:
            connection.rollback()
            result.errors.append(f"{exc.code}: {str(exc)[:80]}")
        except Exception as exc:  # noqa: BLE001 - one document must not kill the sweep
            connection.rollback()
            result.errors.append(f"{type(exc).__name__}: {str(exc)[:80]}")

    result.persisted = stats.inserted + stats.updated
    result.fulltext = stats.fulltext_accepted
    result.metadata_only = stats.metadata_only
    result.rejected = stats.rejected

    # "Nothing new since last run" is the steady state of a healthy source, not
    # a reason to demote it. Only an unexplained empty response is suspicious.
    healthy_empty = {
        "PUBLISHER_SKIP_DAY",
        "NO_NEW_RELEASES",
        "NO_NEW_ENTRIES",
        "NO_NEW_MODELS",
        "NO_CHANGED_SECTIONS",
        "NO_DOC_CHANGES",
        "NO_NEW_ARTICLES",
    }

    # The verdict is about the *source*, not about this one poll. The scheduler
    # runs every two minutes, so a healthy low-volume feed routinely returns one
    # new article or none — and judging it on that alone marked five working
    # sources DEGRADED and thirteen PROBING while every one of them had
    # `consecutive_failures = 0`, no error code, and a success minutes earlier.
    # `_state_from_evidence` already asks the right question; it was simply only
    # consulted in one branch.
    if stats.fulltext_accepted >= 2:
        result.state = "ACTIVE"
    elif stats.fulltext_accepted == 1:
        # One accepted document is a small poll, not a degradation. A source
        # that has cleared the gate before keeps the verdict it earned.
        result.state = _state_from_evidence(connection, source.id) or "PROBING"
    elif stats.metadata_only:
        result.state = "METADATA_ONLY"
    elif not batch.items:
        if batch.not_modified or batch.empty_reason in healthy_empty:
            # Preserve the verdict the source already earned.
            result.state = _state_from_evidence(connection, source.id) or "PROBING"
        else:
            result.state = "PROBING"
    elif stats.rejected:
        # Documents were fetched and the gate turned them down. That is a real
        # signal about the source — it has started serving pages the extractor
        # cannot read — and it stands on its own.
        result.state = "DEGRADED"
    else:
        # Items appeared in the feed but none reached the gate: every one was
        # already stored. That is what a healthy feed looks like when polled
        # more often than it publishes, and four sources with 11-16 accepted
        # documents each sat in DEGRADED because of it.
        result.state = _state_from_evidence(connection, source.id) or "PROBING"

    finish_crawl_run(
        connection,
        run_id,
        status="SUCCESS",
        stats=stats,
        discovered=result.discovered,
        http_status=batch.http_status,
    )
    # Cursor last: only content that actually committed is treated as seen.
    if batch.next_cursor and not batch.not_modified:
        save_cursor(connection, source.id, batch.next_cursor)
    update_source_state(connection, source.id, state=result.state)
    connection.commit()

    return result


def _load_sources(limit: int, profile: str | None, source_id: str | None) -> list[SourceConfig]:
    query = """
        SELECT id, name, organization, profile, source_tier, priority, content_access,
               verification, configured_enabled, discovery_url, repository, subject,
               homepage_url, region, source_group
          FROM source
         WHERE configured_enabled
    """
    params: list[Any] = []
    if profile:
        query += " AND profile = %s"
        params.append(profile)
    if source_id:
        query += " AND id = %s"
        params.append(source_id)
    query += " ORDER BY priority, id LIMIT %s"
    params.append(limit)

    with (
        psycopg.connect(get_settings().database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(query, params)
        rows = cursor.fetchall()

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


async def run_ingest(
    *,
    limit: int,
    profile: str | None,
    source_id: str | None,
    max_documents: int,
    output: str | None,
) -> int:
    import os
    from pathlib import Path

    sources = _load_sources(limit, profile, source_id)
    token = os.environ.get("GITHUB_TOKEN") or None

    results: list[SourceResult] = []
    with psycopg.connect(get_settings().database_url) as connection:
        async with HttpFetcher(HttpConfig()) as fetcher:
            for source in sources:
                results.append(
                    await ingest_source(
                        source, fetcher, connection, token=token, max_documents=max_documents
                    )
                )
                await asyncio.sleep(0.3)

    states: dict[str, int] = {}
    for item in results:
        states[item.state] = states.get(item.state, 0) + 1

    report = {
        "sources": len(results),
        "states": dict(sorted(states.items())),
        "persisted": sum(r.persisted for r in results),
        "fulltext": sum(r.fulltext for r in results),
        "metadata_only": sum(r.metadata_only for r in results),
        "rejected": sum(r.rejected for r in results),
        "detail": [asdict(r) for r in results],
    }

    if output:
        Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        json.dumps({k: v for k, v in report.items() if k != "detail"}, indent=2, ensure_ascii=False)
    )
    return 0

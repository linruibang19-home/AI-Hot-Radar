"""Source probing.

Implements the activation gate from AHR-SOURCE-900 §5: a source only becomes
ACTIVE when discovery succeeds and at least 2 of its latest 3 documents yield
acceptable fulltext.

The report distinguishes three outcomes that are easy to conflate:

* ACTIVE          - discovery works and real fulltext was obtained
* METADATA_ONLY   - discovery works but only titles/abstracts are available
* DEGRADED        - discovery works and fulltext consistently fails
* QUARANTINED     - discovery itself failed

`metadata_only` must never count toward the fulltext success rate (§8).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from ahr.config import get_settings
from ahr.ingestion.adapters.arxiv import ArxivPaperAdapter
from ahr.ingestion.adapters.github_releases import GitHubReleasesAdapter
from ahr.ingestion.adapters.rss import RssAtomAdapter
from ahr.ingestion.article import extract_article
from ahr.ingestion.errors import IngestionError
from ahr.ingestion.fulltext_gate import Decision, ExtractedDocument, evaluate
from ahr.ingestion.http import HttpFetcher, HttpConfig
from ahr.ingestion.models import SourceConfig

# How many recent documents to check per source. §5 requires 2 of the latest 3.
SAMPLE_SIZE = 3
REQUIRED_PASSES = 2


@dataclass
class DocumentOutcome:
    title: str | None
    url: str
    body_chars: int
    decision: str
    reason_code: str | None = None
    error: str | None = None


@dataclass
class SourceOutcome:
    source_id: str
    profile: str
    priority: str
    state: str
    discovered: int = 0
    http_status: int | None = None
    empty_reason: str | None = None
    fulltext_passed: int = 0
    fulltext_sampled: int = 0
    error_code: str | None = None
    error_detail: str | None = None
    documents: list[DocumentOutcome] = field(default_factory=list)


def _adapter_for(source: SourceConfig, fetcher: HttpFetcher, token: str | None) -> Any:
    if source.profile == "github_release_api":
        return GitHubReleasesAdapter(fetcher, token=token, page_limit=1)
    if source.profile == "arxiv_feed_paper":
        return ArxivPaperAdapter(fetcher)
    if source.profile in ("rss_to_article", "author_feed_to_article"):
        return RssAtomAdapter(fetcher)
    return None


async def probe_source(
    source: SourceConfig, fetcher: HttpFetcher, *, token: str | None = None
) -> SourceOutcome:
    outcome = SourceOutcome(
        source_id=source.id, profile=source.profile, priority=source.priority, state="CONFIGURED"
    )

    adapter = _adapter_for(source, fetcher, token)
    if adapter is None:
        outcome.state = "UNSUPPORTED_PROFILE"
        return outcome

    try:
        batch = await adapter.discover(source)
    except IngestionError as exc:
        # Quota exhaustion says nothing about source health, so it must not
        # look like a permanent failure in the report.
        outcome.state = "RATE_LIMITED" if exc.code == "RATE_LIMITED" else "QUARANTINED"
        outcome.error_code = exc.code
        outcome.error_detail = str(exc)[:200]
        return outcome
    except Exception as exc:  # noqa: BLE001 - probe must never crash the sweep
        outcome.state = "QUARANTINED"
        outcome.error_code = "UNEXPECTED"
        outcome.error_detail = f"{type(exc).__name__}: {exc}"[:200]
        return outcome

    outcome.discovered = len(batch.items)
    outcome.http_status = batch.http_status
    outcome.empty_reason = batch.empty_reason

    if not batch.items:
        # A publisher skip day is healthy; an unexplained empty feed is not.
        outcome.state = "ACTIVE" if batch.empty_reason == "PUBLISHER_SKIP_DAY" else "PROBING"
        return outcome

    for item in batch.items[:SAMPLE_SIZE]:
        outcome.fulltext_sampled += 1
        try:
            if not item.requires_fetch:
                # GitHub releases and changelog sections arrive complete.
                document = ExtractedDocument(
                    body_text=item.body_markdown or "",
                    title=item.title_hint,
                    canonical_url=item.candidate_url,
                    published_at=item.published_at_hint,
                    source_id=source.id,
                    extractor="api_body",
                )
                result = evaluate(document, is_release=True)
            else:
                response = await fetcher.fetch(item.candidate_url)
                extraction = extract_article(
                    response,
                    source_id=source.id,
                    title_hint=item.title_hint,
                    published_hint=item.published_at_hint,
                )
                document = extraction.document
                result = evaluate(document, is_release=source.is_release_like)

            if result.decision is Decision.ACCEPTED:
                outcome.fulltext_passed += 1

            outcome.documents.append(
                DocumentOutcome(
                    title=(item.title_hint or "")[:80],
                    url=item.candidate_url,
                    body_chars=result.body_chars,
                    decision=result.decision.value,
                    reason_code=result.reason_code,
                )
            )
        except IngestionError as exc:
            outcome.documents.append(
                DocumentOutcome(
                    title=(item.title_hint or "")[:80],
                    url=item.candidate_url,
                    body_chars=0,
                    decision="ERROR",
                    error=exc.code,
                )
            )
        except Exception as exc:  # noqa: BLE001
            outcome.documents.append(
                DocumentOutcome(
                    title=(item.title_hint or "")[:80],
                    url=item.candidate_url,
                    body_chars=0,
                    decision="ERROR",
                    error=f"{type(exc).__name__}",
                )
            )

    if outcome.fulltext_passed >= REQUIRED_PASSES:
        outcome.state = "ACTIVE"
    elif any(doc.decision == Decision.METADATA_ONLY.value for doc in outcome.documents):
        outcome.state = "METADATA_ONLY"
    else:
        outcome.state = "DEGRADED"

    return outcome


def _load_from_db(limit: int, profile: str | None) -> list[SourceConfig]:
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
    query += " ORDER BY priority, id LIMIT %s"
    params.append(limit)

    with psycopg.connect(get_settings().database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()

    return [
        SourceConfig(
            id=r[0], name=r[1], organization=r[2], profile=r[3], tier=r[4], priority=r[5],
            content_access=r[6], verification=r[7], enabled=r[8], discovery_url=r[9],
            repository=r[10], subject=r[11], homepage_url=r[12], region=r[13], group=r[14],
        )
        for r in rows
    ]


async def run_probe(*, limit: int, profile: str | None, output: str | None) -> int:
    import os

    sources = _load_from_db(limit, profile)
    token = os.environ.get("GITHUB_TOKEN") or None

    outcomes: list[SourceOutcome] = []
    async with HttpFetcher(HttpConfig()) as fetcher:
        for source in sources:
            outcomes.append(await probe_source(source, fetcher, token=token))
            # Be a polite citizen of shared infrastructure.
            await asyncio.sleep(0.5)

    states: dict[str, int] = {}
    for outcome in outcomes:
        states[outcome.state] = states.get(outcome.state, 0) + 1

    total_sampled = sum(o.fulltext_sampled for o in outcomes)
    total_passed = sum(o.fulltext_passed for o in outcomes)

    report = {
        "probed": len(outcomes),
        "states": dict(sorted(states.items())),
        "documents_sampled": total_sampled,
        "documents_with_fulltext": total_passed,
        "fulltext_rate": round(total_passed / total_sampled, 4) if total_sampled else 0.0,
        "sources": [asdict(o) for o in outcomes],
    }

    if output:
        Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {k: v for k, v in report.items() if k != "sources"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0

"""arXiv paper adapter.

AHR-INGEST-1000 §8: RSS discovers papers, then `/html/{id}` is preferred for
fulltext with `/pdf/{id}` as the fallback. The RSS summary is the abstract and
is stored as such — never as the paper body.

arXiv publishes on weekdays only (`<skipDays>Saturday Sunday</skipDays>`), so an
empty feed at the weekend is expected and must not be scored as a failure.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import feedparser

from ahr.ingestion.adapters.rss import _entry_time, _entry_url
from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceConfig, SourceCursor

RSS_ROOT = "https://rss.arxiv.org/rss"
ABS_ROOT = "https://arxiv.org/abs"
HTML_ROOT = "https://arxiv.org/html"
PDF_ROOT = "https://arxiv.org/pdf"

# Matches 2401.12345v2 and the pre-2007 form cs/0701001.
_ARXIV_ID_RE = re.compile(r"(?:abs|html|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?|[a-z-]+/[0-9]{7})")

# arXiv asks for roughly one request every three seconds.
DEFAULT_RATE_LIMIT_SECONDS = 3.0


def extract_arxiv_id(url: str) -> str | None:
    match = _ARXIV_ID_RE.search(url)
    return match.group(1) if match else None


_SKIP_DAY_RE = re.compile(r"<day>\s*([A-Za-z]+)\s*</day>", re.IGNORECASE)


def skip_days(feed_body: bytes) -> set[str]:
    """Days on which the publisher declares it does not publish.

    feedparser flattens `<skipDays>` to an empty string rather than exposing the
    nested `<day>` elements, so this reads them from the raw XML.
    """
    text = feed_body.decode("utf-8", errors="replace")
    return {match.group(1).strip().lower() for match in _SKIP_DAY_RE.finditer(text)}


def is_skip_day_now(days: set[str], *, today: str | None = None) -> bool:
    current = today or datetime.now(UTC).strftime("%A").lower()
    return current in days


class ArxivPaperAdapter:
    """Discovers papers for one arXiv subject feed."""

    name = "arxiv_feed_paper"

    def __init__(self, fetcher: Any) -> None:
        self._fetcher = fetcher

    async def discover(
        self, source: SourceConfig, cursor: SourceCursor | None = None
    ) -> DiscoveryBatch:
        subject = source.subject
        if not subject and source.discovery_url:
            subject = source.discovery_url.rstrip("/").rsplit("/", 1)[-1]
        if not subject:
            raise ParseFailedError(f"source {source.id} has no arXiv subject")

        cursor = cursor or SourceCursor()
        response = await self._fetcher.fetch(
            f"{RSS_ROOT}/{subject}",
            headers={"Accept": "application/rss+xml, application/xml"},
            etag=cursor.etag,
            last_modified=cursor.last_modified,
        )

        if response.not_modified:
            return DiscoveryBatch.unchanged(cursor)

        feed = feedparser.parse(response.body)
        if feed.bozo and not feed.entries:
            raise ParseFailedError(
                f"failed to parse arXiv feed {subject}: {feed.get('bozo_exception')}"
            )

        items: list[DiscoveredDocument] = []
        newest_seen = cursor.newest_entry_time

        for entry in feed.entries:
            url = _entry_url(entry)
            if not url:
                continue
            arxiv_id = extract_arxiv_id(url) or entry.get("id", "").split("/")[-1]
            if not arxiv_id:
                continue

            published = _entry_time(entry)
            if cursor.newest_entry_time and published and published <= cursor.newest_entry_time:
                continue
            if published and (newest_seen is None or published > newest_seen):
                newest_seen = published

            items.append(
                DiscoveredDocument(
                    external_id=arxiv_id,
                    # Cite the abstract page; HTML/PDF are fulltext sources, not
                    # the canonical reference.
                    candidate_url=f"{ABS_ROOT}/{arxiv_id}",
                    title_hint=entry.get("title"),
                    published_at_hint=published,
                    # The RSS summary is the abstract, not the paper body.
                    discovery_summary=entry.get("summary") or entry.get("description"),
                    requires_fetch=True,
                    attributes={
                        "arxiv_id": arxiv_id,
                        "html_url": f"{HTML_ROOT}/{arxiv_id}",
                        "pdf_url": f"{PDF_ROOT}/{arxiv_id}",
                        "subject": subject,
                    },
                )
            )

        empty_reason = None
        if not items:
            # Distinguish "arXiv does not publish today" from "the source broke".
            if not feed.entries and is_skip_day_now(skip_days(response.body)):
                empty_reason = "PUBLISHER_SKIP_DAY"
            elif feed.entries:
                empty_reason = "NO_NEW_ENTRIES"
            else:
                empty_reason = "FEED_EMPTY"

        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(
                etag=response.etag,
                last_modified=response.last_modified,
                newest_entry_time=newest_seen,
                extra={"subject": subject},
            ),
            http_status=response.status_code,
            empty_reason=empty_reason,
        )

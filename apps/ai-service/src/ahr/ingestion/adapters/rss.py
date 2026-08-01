"""RSS/Atom discovery adapter.

AHR-INGEST-1000 §3 is emphatic that a feed only *discovers* content: the entry
summary is stored as `discovery_summary` and never as `body_text`. The article
body comes from a follow-up fetch of the canonical page.

An empty feed is not a failure. arXiv declares `<skipDays>Saturday Sunday</skipDays>`
and legitimately returns zero entries at weekends; treating that as an error
would quarantine a healthy source.
"""

from __future__ import annotations

from calendar import timegm
from datetime import UTC, datetime
from typing import Any

import feedparser

from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceConfig, SourceCursor
from ahr.ingestion.urls import canonicalize_url, url_hash


def _entry_time(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(timegm(parsed), tz=UTC)
    return None


def _entry_url(entry: Any) -> str | None:
    link = entry.get("link")
    if link:
        return str(link)
    # Atom entries may only expose links through the `links` collection.
    for candidate in entry.get("links", []):
        if candidate.get("rel") in (None, "alternate") and candidate.get("href"):
            return str(candidate["href"])
    return None


def _external_id(entry: Any, canonical: str) -> str:
    """`entry.id ?? entry.guid ?? sha256(canonical_link)` per the profile."""
    for key in ("id", "guid"):
        value = entry.get(key)
        if value:
            return str(value)
    return url_hash(canonical)


class RssAtomAdapter:
    """Discovers entries from an RSS or Atom feed."""

    name = "rss_to_article"

    def __init__(self, fetcher: Any) -> None:
        self._fetcher = fetcher

    async def discover(
        self, source: SourceConfig, cursor: SourceCursor | None = None
    ) -> DiscoveryBatch:
        if not source.discovery_url:
            raise ParseFailedError(f"source {source.id} has no discovery_url")

        cursor = cursor or SourceCursor()
        response = await self._fetcher.fetch(
            source.discovery_url,
            headers={
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"
            },
            etag=cursor.etag,
            last_modified=cursor.last_modified,
        )

        if response.not_modified:
            return DiscoveryBatch.unchanged(cursor)

        feed = feedparser.parse(response.body)
        # `bozo` flags malformed XML. Many real feeds trip it on encoding quirks
        # while still parsing, so only a total absence of entries is fatal.
        if feed.bozo and not feed.entries:
            raise ParseFailedError(
                f"failed to parse feed {source.discovery_url}: {feed.get('bozo_exception')}"
            )

        items: list[DiscoveredDocument] = []
        newest_seen = cursor.newest_entry_time

        for entry in feed.entries:
            raw_url = _entry_url(entry)
            if not raw_url:
                continue
            try:
                canonical = canonicalize_url(raw_url)
            except ValueError:
                # A single malformed link must not abort the whole batch.
                continue

            published = _entry_time(entry)
            if cursor.newest_entry_time and published and published <= cursor.newest_entry_time:
                continue

            if published and (newest_seen is None or published > newest_seen):
                newest_seen = published

            items.append(
                DiscoveredDocument(
                    external_id=_external_id(entry, canonical),
                    candidate_url=canonical,
                    title_hint=entry.get("title"),
                    published_at_hint=published,
                    # Stored for provenance only. Never promoted to body_text.
                    discovery_summary=entry.get("summary") or entry.get("description"),
                    requires_fetch=True,
                )
            )

        empty_reason = None
        if not items:
            empty_reason = "NO_NEW_ENTRIES" if feed.entries else "FEED_EMPTY"

        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(
                etag=response.etag,
                last_modified=response.last_modified,
                newest_entry_time=newest_seen,
            ),
            http_status=response.status_code,
            empty_reason=empty_reason,
        )

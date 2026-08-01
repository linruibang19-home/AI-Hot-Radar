"""GitHub Releases adapter.

AHR-INGEST-1000 §4: the REST `body` field is the complete release note, so no
follow-up article fetch is needed. Covers 53 of the 140 configured sources.

Field mapping is fixed by the spec:
    id -> external_id, html_url -> canonical_url, name ?? tag_name -> title,
    body -> body_markdown, published_at -> published_at,
    draft -> skipped, prerelease -> attributes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.http import FetchResult, HttpFetcher
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceConfig, SourceCursor

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"

# RFC 8288 Link header: <url>; rel="next"
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def next_page_url(link_header: str | None) -> str | None:
    """Extract the `rel="next"` URL, or None on the last page."""
    if not link_header:
        return None
    match = _LINK_NEXT.search(link_header)
    return match.group(1) if match else None


def rate_limit_remaining(headers: dict[str, str]) -> int | None:
    raw = headers.get("x-ratelimit-remaining")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class GitHubReleasesAdapter:
    """Discovers releases for one repository."""

    name = "github_release_api"

    def __init__(self, fetcher: HttpFetcher, *, token: str | None = None, page_limit: int = 5) -> None:
        self._fetcher = fetcher
        self._token = token
        self._page_limit = page_limit

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def discover(self, source: SourceConfig, cursor: SourceCursor | None = None) -> DiscoveryBatch:
        if not source.repository:
            raise ParseFailedError(f"source {source.id} has no repository")

        cursor = cursor or SourceCursor()
        url: str | None = f"{API_ROOT}/repos/{source.repository}/releases?per_page=100"

        items: list[DiscoveredDocument] = []
        newest_seen = cursor.newest_entry_time
        first_response: FetchResult | None = None
        stop = False

        for _ in range(self._page_limit):
            if url is None or stop:
                break

            # The conditional request only applies to the first page; later
            # pages are distinct resources with their own validators.
            response = await self._fetcher.fetch(
                url,
                headers=self._headers(),
                etag=cursor.etag if first_response is None else None,
            )
            if first_response is None:
                first_response = response
                if response.not_modified:
                    return DiscoveryBatch.unchanged(cursor)

            try:
                payload: Any = json.loads(response.text())
            except json.JSONDecodeError as exc:
                raise ParseFailedError(f"invalid JSON from {url}: {exc}") from exc

            if not isinstance(payload, list):
                raise ParseFailedError(f"expected a JSON array from {url}")

            for release in payload:
                if release.get("draft"):
                    continue

                published_at = _parse_iso8601(release.get("published_at"))
                # Releases arrive newest-first; once we reach content we have
                # already ingested, later pages are older still.
                if cursor.newest_entry_time and published_at and published_at <= cursor.newest_entry_time:
                    stop = True
                    break

                html_url = release.get("html_url")
                if not html_url:
                    continue

                if published_at and (newest_seen is None or published_at > newest_seen):
                    newest_seen = published_at

                items.append(
                    DiscoveredDocument(
                        external_id=str(release.get("id")),
                        candidate_url=html_url,
                        title_hint=release.get("name") or release.get("tag_name"),
                        published_at_hint=published_at,
                        # The API body IS the release note; there is nothing to fetch.
                        body_markdown=release.get("body") or "",
                        requires_fetch=False,
                        attributes={
                            "tag_name": release.get("tag_name"),
                            "prerelease": bool(release.get("prerelease")),
                            "repository": source.repository,
                        },
                    )
                )

            url = next_page_url(response.headers.get("link"))

        assert first_response is not None
        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(
                etag=first_response.etag,
                last_modified=first_response.last_modified,
                newest_entry_time=newest_seen,
                extra={"rate_limit_remaining": rate_limit_remaining(first_response.headers)},
            ),
            http_status=first_response.status_code,
            empty_reason="NO_NEW_RELEASES" if not items else None,
        )

"""GitHub Releases adapter tests (AHR-INGEST-1000 §4). Offline via MockTransport."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from ahr.ingestion.adapters.github_releases import (
    GitHubReleasesAdapter,
    next_page_url,
    rate_limit_remaining,
)
from ahr.ingestion.errors import RateLimitedError
from ahr.ingestion.models import SourceConfig, SourceCursor


def source(repository: str = "octo/repo") -> SourceConfig:
    return SourceConfig(
        id="octo-releases",
        name="Octo Releases",
        organization="Octo",
        profile="github_release_api",
        tier="primary",
        priority="P0",
        content_access="full_release_text",
        verification="protocol_guaranteed",
        enabled=True,
        repository=repository,
    )


def release(
    release_id: int, *, published: str, body: str = "Release notes body", draft: bool = False
) -> dict:
    return {
        "id": release_id,
        "html_url": f"https://github.com/octo/repo/releases/tag/v{release_id}",
        "name": f"v{release_id}",
        "tag_name": f"v{release_id}",
        "body": body,
        "published_at": published,
        "draft": draft,
        "prerelease": False,
    }


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('<https://api.github.com/x?page=2>; rel="next"', "https://api.github.com/x?page=2"),
        ('<https://api.github.com/x?page=1>; rel="prev"', None),
        (None, None),
        ("", None),
    ],
)
def test_next_page_url(header: str | None, expected: str | None) -> None:
    assert next_page_url(header) == expected


def test_rate_limit_remaining_parses_header() -> None:
    assert rate_limit_remaining({"x-ratelimit-remaining": "42"}) == 42
    assert rate_limit_remaining({}) is None
    assert rate_limit_remaining({"x-ratelimit-remaining": "nonsense"}) is None


async def test_discovers_releases_with_full_body(make_fetcher) -> None:
    payload = [
        release(2, published="2026-07-31T10:00:00Z"),
        release(1, published="2026-07-30T10:00:00Z"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, headers={"ETag": '"abc"'})

    async with make_fetcher(handler) as fetcher:
        batch = await GitHubReleasesAdapter(fetcher).discover(source())

    assert len(batch.items) == 2
    assert batch.items[0].external_id == "2"
    # The API body is the release note; no follow-up fetch is required.
    assert batch.items[0].requires_fetch is False
    assert batch.items[0].body_markdown == "Release notes body"
    assert batch.next_cursor is not None and batch.next_cursor.etag == '"abc"'


async def test_draft_releases_are_skipped(make_fetcher) -> None:
    payload = [
        release(3, published="2026-07-31T10:00:00Z", draft=True),
        release(2, published="2026-07-30T10:00:00Z"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with make_fetcher(handler) as fetcher:
        batch = await GitHubReleasesAdapter(fetcher).discover(source())

    assert [item.external_id for item in batch.items] == ["2"]


async def test_not_modified_returns_unchanged_batch(make_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("If-None-Match") == '"cached"'
        return httpx.Response(304)

    async with make_fetcher(handler) as fetcher:
        batch = await GitHubReleasesAdapter(fetcher).discover(
            source(), SourceCursor(etag='"cached"')
        )

    assert batch.not_modified is True
    assert batch.items == []


async def test_cursor_stops_at_already_seen_release(make_fetcher) -> None:
    """Replaying the same feed must not re-emit known releases."""
    payload = [
        release(2, published="2026-07-31T10:00:00Z"),
        release(1, published="2026-07-30T10:00:00Z"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    cursor = SourceCursor(newest_entry_time=datetime(2026, 7, 31, 10, 0, tzinfo=UTC))
    async with make_fetcher(handler) as fetcher:
        batch = await GitHubReleasesAdapter(fetcher).discover(source(), cursor)

    assert batch.items == []
    assert batch.empty_reason == "NO_NEW_RELEASES"


async def test_pagination_follows_link_header(make_fetcher) -> None:
    pages = {
        1: [release(4, published="2026-07-31T10:00:00Z")],
        2: [release(3, published="2026-07-30T10:00:00Z")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        headers = {}
        if page == 1:
            headers["Link"] = '<https://api.github.com/repos/octo/repo/releases?page=2>; rel="next"'
        return httpx.Response(200, json=pages[page], headers=headers)

    async with make_fetcher(handler) as fetcher:
        batch = await GitHubReleasesAdapter(fetcher, page_limit=3).discover(source())

    assert [item.external_id for item in batch.items] == ["4", "3"]


async def test_quota_exhaustion_is_retryable_not_access_denied(make_fetcher) -> None:
    """Regression: GitHub returns 403 with a zeroed quota rather than 429.

    Classifying that as ACCESS_RESTRICTED permanently quarantined healthy
    sources.
    """
    reset_at = str(int(datetime.now(UTC).timestamp()) + 120)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset_at},
        )

    async with make_fetcher(handler) as fetcher:
        with pytest.raises(RateLimitedError) as excinfo:
            await GitHubReleasesAdapter(fetcher).discover(source())

    assert excinfo.value.retryable is True
    assert excinfo.value.retry_after is not None


async def test_empty_release_body_still_discovered(make_fetcher) -> None:
    """A release with no body keeps its metadata but must not count as fulltext."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[release(9, published="2026-07-31T10:00:00Z", body="")])

    async with make_fetcher(handler) as fetcher:
        batch = await GitHubReleasesAdapter(fetcher).discover(source())

    assert len(batch.items) == 1
    assert batch.items[0].body_markdown == ""


async def test_invalid_json_raises_parse_failed(make_fetcher) -> None:
    from ahr.ingestion.errors import ParseFailedError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    async with make_fetcher(handler) as fetcher:
        with pytest.raises(ParseFailedError):
            await GitHubReleasesAdapter(fetcher).discover(source())

"""RSS/Atom and arXiv adapter tests (AHR-INGEST-1000 §3, §8). Offline fixtures."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import httpx
import pytest

from ahr.ingestion.adapters.arxiv import (
    ArxivPaperAdapter,
    extract_arxiv_id,
    is_skip_day_now,
    skip_days,
)
from ahr.ingestion.adapters.rss import RssAtomAdapter
from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.fulltext_gate import Decision, evaluate
from ahr.ingestion.models import DiscoveredDocument, SourceConfig, SourceCursor
from ahr.ingestion.urls import url_hash


def feed_source() -> SourceConfig:
    return SourceConfig(
        id="example-blog",
        name="Example Blog",
        organization="Example",
        profile="rss_to_article",
        tier="primary",
        priority="P0",
        content_access="full_article_extract",
        verification="protocol_guaranteed",
        enabled=True,
        discovery_url="https://example.com/feed.xml",
    )


def arxiv_source() -> SourceConfig:
    return SourceConfig(
        id="arxiv-cs-ai",
        name="arXiv cs.AI",
        organization="arXiv",
        profile="arxiv_feed_paper",
        tier="primary",
        priority="P0",
        content_access="full_paper",
        verification="protocol_guaranteed",
        enabled=True,
        subject="cs.AI",
    )


def arxiv_item() -> DiscoveredDocument:
    return DiscoveredDocument(
        external_id="2608.01234",
        candidate_url="https://arxiv.org/abs/2608.01234",
        title_hint="Evidence Grounded Retrieval for Time-Sensitive AI Intelligence",
        published_at_hint=datetime(2026, 8, 3, tzinfo=UTC),
        discovery_summary="This is the abstract, not the body.",
        attributes={
            "arxiv_id": "2608.01234",
            "html_url": "https://arxiv.org/html/2608.01234",
            "pdf_url": "https://arxiv.org/pdf/2608.01234",
        },
    )


async def test_discovers_entries(make_fetcher, fixture_bytes) -> None:
    body = fixture_bytes("sample_feed.xml")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"ETag": '"feed-1"'})

    async with make_fetcher(handler) as fetcher:
        batch = await RssAtomAdapter(fetcher).discover(feed_source())

    assert len(batch.items) == 3
    assert batch.items[0].external_id == "post-2"
    # Every discovered entry still needs its article fetched.
    assert all(item.requires_fetch for item in batch.items)


async def test_feed_summary_is_never_body_text(make_fetcher, fixture_bytes) -> None:
    """The teaser belongs in discovery_summary only (AHR-INGEST-1000 §3.9)."""
    body = fixture_bytes("sample_feed.xml")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with make_fetcher(handler) as fetcher:
        batch = await RssAtomAdapter(fetcher).discover(feed_source())

    item = batch.items[0]
    assert item.discovery_summary is not None
    assert "teaser" in item.discovery_summary
    assert item.body_markdown is None


async def test_tracking_params_are_stripped_from_candidate_url(make_fetcher, fixture_bytes) -> None:
    body = fixture_bytes("sample_feed.xml")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with make_fetcher(handler) as fetcher:
        batch = await RssAtomAdapter(fetcher).discover(feed_source())

    assert batch.items[0].candidate_url == "https://example.com/blog/second"


async def test_missing_guid_falls_back_to_link_hash(make_fetcher, fixture_bytes) -> None:
    body = fixture_bytes("sample_feed.xml")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with make_fetcher(handler) as fetcher:
        batch = await RssAtomAdapter(fetcher).discover(feed_source())

    no_guid = batch.items[2]
    assert no_guid.external_id == url_hash("https://example.com/blog/no-guid")


async def test_not_modified_returns_unchanged(make_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("If-None-Match") == '"feed-1"'
        return httpx.Response(304)

    async with make_fetcher(handler) as fetcher:
        batch = await RssAtomAdapter(fetcher).discover(feed_source(), SourceCursor(etag='"feed-1"'))

    assert batch.not_modified is True
    assert batch.items == []


async def test_replaying_same_feed_yields_no_duplicates(make_fetcher, fixture_bytes) -> None:
    body = fixture_bytes("sample_feed.xml")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    cursor = SourceCursor(newest_entry_time=datetime(2026, 7, 31, 10, 0, tzinfo=UTC))
    async with make_fetcher(handler) as fetcher:
        batch = await RssAtomAdapter(fetcher).discover(feed_source(), cursor)

    assert batch.items == []
    assert batch.empty_reason == "NO_NEW_ENTRIES"


async def test_malformed_feed_raises_parse_failed(make_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<<<not xml at all")

    async with make_fetcher(handler) as fetcher:
        with pytest.raises(ParseFailedError):
            await RssAtomAdapter(fetcher).discover(feed_source())


# --- arXiv ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://arxiv.org/abs/2401.12345", "2401.12345"),
        ("https://arxiv.org/abs/2401.12345v2", "2401.12345v2"),
        ("https://arxiv.org/abs/cs/0701001", "cs/0701001"),
        ("https://example.com/x", None),
    ],
)
def test_extract_arxiv_id(url: str, expected: str | None) -> None:
    assert extract_arxiv_id(url) == expected


def test_skip_days_parsed_from_raw_xml(fixture_bytes) -> None:
    """feedparser flattens <skipDays>, so the days come from the raw XML."""
    assert skip_days(fixture_bytes("arxiv_weekend.xml")) == {"saturday", "sunday"}


def test_is_skip_day_now() -> None:
    days = {"saturday", "sunday"}
    assert is_skip_day_now(days, today="saturday") is True
    assert is_skip_day_now(days, today="monday") is False


async def test_weekend_empty_feed_is_not_a_failure(make_fetcher, fixture_bytes) -> None:
    """arXiv publishes on weekdays only; an empty weekend feed is healthy."""
    body = fixture_bytes("arxiv_weekend.xml")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with make_fetcher(handler) as fetcher:
        batch = await ArxivPaperAdapter(fetcher).discover(arxiv_source())

    assert batch.items == []
    # Only meaningful on an actual skip day; otherwise the reason differs.
    assert batch.empty_reason in {"PUBLISHER_SKIP_DAY", "FEED_EMPTY"}


async def test_arxiv_prefers_replayable_html_fulltext(make_fetcher, fixture_bytes) -> None:
    html = fixture_bytes("arxiv_paper.html")
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=html, headers={"content-type": "text/html"})

    async with make_fetcher(handler) as fetcher:
        acquired = await ArxivPaperAdapter(fetcher, rate_limit_seconds=0).acquire(
            arxiv_item(), source_id="arxiv-cs-ai"
        )

    assert requested == ["https://arxiv.org/html/2608.01234"]
    assert acquired.requested_url.endswith("/html/2608.01234")
    assert acquired.extraction.document.canonical_url.endswith("/abs/2608.01234")
    assert acquired.extraction.document.extractor == "arxiv_html"
    assert evaluate(acquired.extraction.document).decision is Decision.ACCEPTED


async def test_arxiv_missing_html_falls_back_to_replayable_pdf(
    make_fetcher, fixture_bytes
) -> None:
    pdf = base64.b64decode(fixture_bytes("arxiv_paper.pdf.b64"))
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if "/html/" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})

    async with make_fetcher(handler) as fetcher:
        acquired = await ArxivPaperAdapter(fetcher, rate_limit_seconds=0).acquire(
            arxiv_item(), source_id="arxiv-cs-ai"
        )

    assert requested == [
        "https://arxiv.org/html/2608.01234",
        "https://arxiv.org/pdf/2608.01234",
    ]
    assert acquired.extraction.document.extractor == "arxiv_pdf_pymupdf"
    assert "[Page 1]" in acquired.extraction.document.body_text
    assert evaluate(acquired.extraction.document).decision is Decision.ACCEPTED


async def test_arxiv_invalid_pdf_is_a_parse_failure(make_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/html/" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=b"not a pdf")

    async with make_fetcher(handler) as fetcher:
        with pytest.raises(ParseFailedError):
            await ArxivPaperAdapter(fetcher, rate_limit_seconds=0).acquire(
                arxiv_item(), source_id="arxiv-cs-ai"
            )

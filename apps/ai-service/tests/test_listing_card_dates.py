"""Listing items take the date their card prints.

Before this, every item from a listing source was stored without a publication
date — 736 of 737 on 2026-09-22 — because the adapter never looked for one and
the article pages that do get fetched carry no per-article date (Anthropic's
fell back to a site-wide 2023-11-03). Retrieval windows on
`COALESCE(published_at, observed_at)`, so an undated item reads as published on
the day it was first crawled. Measured on the live listings on 2026-09-28:
Anthropic 10 of 11 links dated, Groq 14 of 14, Cerebras 48 of 49, Cohere 22 of
57, Hugging Face blog 16 of 57; every spot-checked date was the publication date.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ahr.ingestion.adapters.listing import HtmlListingAdapter, card_date, listing_card_dates
from ahr.ingestion.models import SourceConfig
from ahr.ingestion.repository import fill_missing_published_at
from ahr.ingestion.urls import canonicalize_url, url_hash

LISTING = "https://www.anthropic.example/news"

# The three layouts seen on real cards: date first (Anthropic), date last
# (Cerebras, Groq), and an image link to the same article that carries no text.
HTML = """
<html><body>
<a href="/news/enzyme"><span>Sep 23, 2026</span><span>Science</span>
  <h3>Claude discovers a novel enzyme system</h3></a>
<a href="/news/accenture"><img src="a.png" alt=""></a>
<a href="/news/accenture"><h3>Partnering with Accenture</h3><time>Sep 18, 2026</time></a>
<a href="/news/undated"><h3>A post whose card prints no date</h3></a>
</body></html>
"""


def _d(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def test_the_formats_real_cards_print() -> None:
    assert card_date("Sep 23, 2026 Science Claude discovers") == _d(2026, 9, 23)
    assert card_date("The rise of slow personal assistants September 24, 2026") == _d(2026, 9, 24)
    assert card_date("Introducing North Mini Code Jun 09, 2026 3 min read") == _d(2026, 6, 9)
    assert card_date("not-lain • 30 Jan 2025 • 422") == _d(2025, 1, 30)
    assert card_date("发布于 2026年9月8日 阅读") == _d(2026, 9, 8)
    assert card_date("更新 2026-09-08") == _d(2026, 9, 8)


def test_two_different_dates_are_no_date() -> None:
    """Which one is the publication date is a guess, and a wrong date is worse
    than none: it moves an old item into every "this week" window."""
    assert card_date("Sep 18, 2026 Announcing DevDay on Oct 6, 2026") is None


def test_the_same_date_twice_is_still_one_date() -> None:
    assert card_date("Sep 18, 2026 · posted 2026-09-18") == _d(2026, 9, 18)


def test_words_that_start_like_months_are_not_months() -> None:
    assert card_date("Mayor 3, 2026 update") is None
    assert card_date("Decision 12, 2026") is None


def test_an_impossible_date_is_ignored() -> None:
    assert card_date("Feb 30, 2026") is None


def _source() -> SourceConfig:
    return SourceConfig(
        id="anthropic-news",
        name="Anthropic Newsroom",
        organization="Anthropic",
        profile="static_listing_to_article",
        tier="primary",
        priority="P0",
        content_access="full_article_extract",
        verification="page_confirmed",
        enabled=True,
        discovery_url=LISTING,
    )


def _serve(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})


async def test_discovered_items_carry_the_card_date(make_fetcher: Any) -> None:
    async with make_fetcher(_serve) as fetcher:
        batch = await HtmlListingAdapter(fetcher).discover(_source())

    dated = {item.candidate_url.rsplit("/", 1)[-1]: item.published_at_hint for item in batch.items}
    assert dated["enzyme"] == _d(2026, 9, 23)
    # The image link came first and has no text; the headline link supplies it.
    assert dated["accenture"] == _d(2026, 9, 18)
    assert dated["undated"] is None


async def test_the_repair_pass_reads_the_same_dates(make_fetcher: Any) -> None:
    async with make_fetcher(_serve) as fetcher:
        dates = await listing_card_dates(fetcher, _source())

    enzyme = url_hash(canonicalize_url("https://www.anthropic.example/news/enzyme"))
    assert dates[enzyme] == _d(2026, 9, 23)
    assert len(dates) == 2


class _Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.rowcount = 1

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = ()) -> None:
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self) -> tuple[int]:
        return (1,)


class _Connection:
    def __init__(self) -> None:
        self.cursor_obj = _Cursor()

    def cursor(self) -> _Cursor:
        return self.cursor_obj


def test_the_repair_only_fills_missing_dates() -> None:
    connection = _Connection()
    filled = fill_missing_published_at(connection, "anthropic-news", {"a": _d(2026, 9, 23)})

    [(sql, params)] = connection.cursor_obj.calls
    assert sql.startswith("UPDATE content_item SET published_at")
    assert sql.endswith("AND published_at IS NULL")
    assert params == (_d(2026, 9, 23), "anthropic-news", "a")
    assert filled == 1


def test_the_repair_drops_dates_that_cannot_be_real() -> None:
    connection = _Connection()
    future = datetime.now(UTC) + timedelta(days=30)
    assert fill_missing_published_at(connection, "s", {"a": future}) == 0
    assert connection.cursor_obj.calls == []


def test_a_dry_run_counts_without_writing() -> None:
    connection = _Connection()
    assert fill_missing_published_at(connection, "s", {"a": _d(2026, 9, 1)}, dry_run=True) == 1
    [(sql, _params)] = connection.cursor_obj.calls
    assert sql.startswith("SELECT count(*)")

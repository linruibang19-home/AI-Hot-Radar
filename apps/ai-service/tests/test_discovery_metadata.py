"""A refused article keeps its discovery record instead of vanishing (ADR-0013).

`openai-news` read its feed on every poll — 154 entries, HTTP 200 — and fetched
none of them: each article answered 403, the item was rolled back, and the run
was recorded as SUCCESS. Eight weeks, zero items, for the first-party source of
the vendor the site is most often asked about. ADR-0013 had decided to keep the
metadata on 2026-08-01; the configuration was never changed and the pipeline
had no branch that could do it.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ahr.ingestion import pipeline
from ahr.ingestion.errors import AccessRestrictedError
from ahr.ingestion.fulltext_gate import DISCOVERY_METADATA, Decision
from ahr.ingestion.models import SourceConfig, SourceCursor
from ahr.processing import pipeline as processing
from ahr.processing.llm import LlmClient, LlmConfig

FEED = "https://openai.example/news/rss.xml"
ARTICLE = "https://openai.example/index/two-years-of-academy"

RSS = f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>News</title>
<item>
  <title>Two years of OpenAI Academy</title>
  <link>{ARTICLE}</link>
  <guid>academy-2</guid>
  <pubDate>Wed, 23 Sep 2026 16:00:00 GMT</pubDate>
  <description>Marking two years of OpenAI Academy and bringing AI skills
    to more communities.</description>
</item>
</channel></rss>""".encode()


def _source(content_access: str) -> SourceConfig:
    return SourceConfig(
        id="openai-news",
        name="OpenAI News",
        organization="OpenAI",
        profile="rss_to_article",
        tier="primary",
        priority="P0",
        content_access=content_access,
        verification="page_confirmed",
        enabled=True,
        discovery_url=FEED,
    )


class _Connection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the persistence layer with a recorder; the pipeline logic runs as is."""
    calls: dict[str, Any] = {"persisted": [], "cursor": None, "state": None}

    def persist(connection: Any, **kwargs: Any) -> None:
        calls["persisted"].append(kwargs)
        stats = kwargs["stats"]
        if kwargs["gate"].decision is Decision.METADATA_ONLY:
            stats.metadata_only += 1
        stats.inserted += 1

    monkeypatch.setattr(pipeline, "persist_document", persist)
    monkeypatch.setattr(pipeline, "load_cursor", lambda *a: SourceCursor())
    monkeypatch.setattr(pipeline, "start_crawl_run", lambda *a, **k: "run-1")
    monkeypatch.setattr(pipeline, "finish_crawl_run", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_state_from_evidence", lambda *a: None)
    monkeypatch.setattr(
        pipeline, "save_cursor", lambda _c, _id, cursor: calls.__setitem__("cursor", cursor)
    )
    monkeypatch.setattr(
        pipeline,
        "update_source_state",
        lambda _c, _id, *, state, **_k: calls.__setitem__("state", state),
    )
    return calls


def _feed_then_403(request: httpx.Request) -> httpx.Response:
    if str(request.url) == FEED:
        return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})
    return httpx.Response(403, content=b"<html>Forbidden</html>")


async def test_a_refused_article_is_kept_as_discovery_metadata(
    make_fetcher: Any, recorded: dict[str, Any]
) -> None:
    connection = _Connection()
    async with make_fetcher(_feed_then_403) as fetcher:
        result = await pipeline.ingest_source(
            _source("metadata_abstract"), fetcher, connection, max_documents=5
        )

    [stored] = recorded["persisted"]
    assert stored["body_text"] == ""
    assert stored["extractor"] == DISCOVERY_METADATA
    assert stored["gate"].decision is Decision.METADATA_ONLY
    assert stored["gate"].reason_code == "ARTICLE_ACCESS_RESTRICTED"
    assert stored["http_status"] == 403
    # What discovery proved is what survives: title, link, time, summary.
    item = stored["item"]
    assert item.title_hint == "Two years of OpenAI Academy"
    assert item.published_at_hint is not None
    assert item.discovery_summary.startswith("Marking two years")

    assert result.metadata_only == 1
    assert result.state == "METADATA_ONLY"
    assert connection.rollbacks == 0
    # Stored means seen: the watermark moves, so the next poll does not ask
    # the publisher for the same refused page again.
    assert recorded["cursor"].newest_entry_time == item.published_at_hint


async def test_a_full_text_source_still_fails_the_item(
    make_fetcher: Any, recorded: dict[str, Any]
) -> None:
    """For a source registered as full text a refusal is a fault. Storing a
    title-only row would count it as working."""
    connection = _Connection()
    async with make_fetcher(_feed_then_403) as fetcher:
        result = await pipeline.ingest_source(
            _source("full_article_extract"), fetcher, connection, max_documents=5
        )

    assert recorded["persisted"] == []
    assert connection.rollbacks == 1
    assert result.errors and result.errors[0].startswith("ACCESS_RESTRICTED")
    # Nothing stored, so nothing is behind the watermark.
    assert recorded["cursor"].newest_entry_time is None


def test_only_metadata_abstract_sources_keep_metadata() -> None:
    assert _source("metadata_abstract").keeps_metadata_when_refused
    for access in ("full_article_extract", "full_release_text", "full_paper", "discovery_only"):
        assert not _source(access).keeps_metadata_when_refused


async def test_the_refusal_carries_the_status_it_answered_with(make_fetcher: Any) -> None:
    async with make_fetcher(lambda request: httpx.Response(401)) as fetcher:
        with pytest.raises(AccessRestrictedError) as refused:
            await fetcher.fetch(ARTICLE)
    assert refused.value.status_code == 401


# --- processing: listed, never chunked ---------------------------------------


class _Cursor:
    rowcount = 0

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = ()) -> None:
        self.queries.append(" ".join(sql.split()))

    def fetchall(self) -> list[Any]:
        return []


class _ProcessingConnection:
    def __init__(self) -> None:
        self.cursor_obj = _Cursor()

    def cursor(self) -> _Cursor:
        return self.cursor_obj

    def commit(self) -> None:
        return None


def test_a_discovery_metadata_item_is_queued_for_enrichment() -> None:
    connection = _ProcessingConnection()
    processing._pending_items(connection, 10)
    sql = connection.cursor_obj.queries[0]
    assert f"cr.extraction_method = '{DISCOVERY_METADATA}'" in sql
    assert "length(cr.body_text) > 0 OR" in sql


def test_a_discovery_metadata_item_is_not_closed_as_empty() -> None:
    connection = _ProcessingConnection()
    processing.close_empty_bodies(connection)
    sql = connection.cursor_obj.queries[0]
    assert f"AND NOT (cr.extraction_method = '{DISCOVERY_METADATA}'" in sql


def test_a_discovery_metadata_item_is_never_chunked() -> None:
    """The line between listing an item and citing it. Chunking selects by
    body, and these bodies are empty by construction."""
    connection = _ProcessingConnection()
    processing._unchunked_revisions(connection, 10)
    sql = connection.cursor_obj.queries[0]
    assert "length(cr.body_text) > 0" in sql
    assert "discovery_summary" not in sql
    assert DISCOVERY_METADATA not in sql


def test_feed_markup_is_stripped_before_the_model_reads_it() -> None:
    assert (
        processing.discovery_text("<p>Marking <b>two</b> years &amp; more.</p>\n")
        == "Marking two years & more."
    )


async def test_the_model_is_told_it_is_reading_a_summary() -> None:
    sent: list[str] = []
    payload = {
        "summary_zh": "OpenAI Academy 迎来两周年。",
        "zh_title": "OpenAI Academy 两周年",
        "content_type": "business",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    client = LlmClient(
        LlmConfig(base_url="https://llm.example", api_key="k", model="m", max_attempts=1),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    async with client:
        await client.enrich(title="t", body_text="简介一句", source_name="s", discovery_only=True)
        await client.enrich(title="t", body_text="正文很长", source_name="s")

    summary_prompt, body_prompt = sent
    assert "未取得正文" in summary_prompt and "简介：\n简介一句" in summary_prompt
    assert "正文：" not in summary_prompt
    assert body_prompt.endswith("正文：\n正文很长")


def test_the_summary_records_what_it_rests_on() -> None:
    """A reader-facing surface can then say "from the publisher's summary"."""
    import uuid
    from unittest.mock import MagicMock

    from ahr.processing.schemas import EnrichmentResult

    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = ("entity-id",)
    result = EnrichmentResult.model_validate(
        {"summary_zh": "摘要。", "zh_title": "标题", "content_type": "business"}
    )

    processing._store_enrichment(
        connection,
        uuid.uuid4(),
        result,
        source_tier="primary",
        model_name="m",
        vocabulary=set(),
        basis="discovery_summary",
    )

    update = next(
        call.args[1]
        for call in cursor.execute.call_args_list
        if call.args[0].lstrip().startswith("UPDATE content_item")
    )
    assert json.loads(update[6])["enrichment_basis"] == "discovery_summary"

"""Daily report rendering and token accounting tests (M2)."""

from __future__ import annotations

import uuid
from datetime import date

import httpx
import pytest

from ahr.processing.llm import LlmClient, LlmConfig, LlmUnavailableError, TokenUsage
from ahr.processing.report import (
    ReportItem,
    _group_by_section,
    _period_range,
    render_markdown,
)

TITLE = "AI Hot Radar 日报 · 2026-08-01"


def item(
    *,
    title: str = "标题",
    content_type: str | None = "model_release",
    summary: str | None = "摘要内容",
    url: str = "https://example.com/a",
    score: float = 80.0,
    story_slug: str | None = None,
    independent_sources: int = 1,
) -> ReportItem:
    return ReportItem(
        item_id=uuid.uuid4(),
        title=title,
        summary=summary,
        source_name="Example Source",
        canonical_url=url,
        content_type=content_type,
        score=score,
        story_slug=story_slug,
        independent_sources=independent_sources,
    )


# --- story collapsing (M3) -------------------------------------------------


def test_one_event_appears_once() -> None:
    """Three outlets covering one release is one entry, not three headlines."""
    from ahr.processing.report import collapse_by_story

    collapsed = collapse_by_story(
        [
            item(title="官方发布", story_slug="s1", score=90),
            item(title="媒体报道", story_slug="s1", score=70),
            item(title="另一家报道", story_slug="s1", score=60),
        ]
    )
    assert len(collapsed) == 1


def test_the_highest_scoring_article_represents_the_event() -> None:
    """Rows arrive score-ordered, so the first seen is the one worth linking."""
    from ahr.processing.report import collapse_by_story

    collapsed = collapse_by_story(
        [
            item(title="官方发布", story_slug="s1", score=90),
            item(title="转载", story_slug="s1", score=40),
        ]
    )
    assert collapsed[0].title == "官方发布"


def test_items_without_a_story_are_all_kept() -> None:
    """Clustering only covers a recent window; older selections have no story
    and must not collapse into each other."""
    from ahr.processing.report import collapse_by_story

    collapsed = collapse_by_story([item(title="甲"), item(title="乙"), item(title="丙")])
    assert len(collapsed) == 3


def test_distinct_stories_are_not_merged() -> None:
    from ahr.processing.report import collapse_by_story

    collapsed = collapse_by_story(
        [item(story_slug="s1"), item(story_slug="s2"), item(story_slug="s3")]
    )
    assert len(collapsed) == 3


def test_corroboration_count_is_rendered() -> None:
    markdown = render_markdown(
        TITLE, "", [("模型发布", [item(title="事件", independent_sources=4)])]
    )
    assert "另有 3 家信源报道" in markdown


def test_single_source_entry_says_nothing_about_corroboration() -> None:
    """Claiming corroboration that does not exist is worse than staying silent."""
    markdown = render_markdown(
        TITLE, "", [("模型发布", [item(title="事件", independent_sources=1)])]
    )
    assert "信源报道" not in markdown


# --- section grouping ----------------------------------------------------


def test_sections_follow_the_declared_order() -> None:
    """Releases lead the report; opinion trails it."""
    sections = _group_by_section([item(content_type="opinion"), item(content_type="model_release")])
    assert [label for label, _ in sections] == ["模型发布", "观点"]


def test_unknown_content_type_still_appears() -> None:
    """An item outside the taxonomy must not silently vanish from the report."""
    sections = _group_by_section([item(content_type="something_new")])
    assert [label for label, _ in sections] == ["其他"]


def test_items_without_content_type_are_kept() -> None:
    sections = _group_by_section([item(content_type=None)])
    assert sections
    assert sum(len(group) for _, group in sections) == 1


def test_no_item_is_lost_across_sections() -> None:
    items = [
        item(content_type="model_release"),
        item(content_type="research"),
        item(content_type=None),
        item(content_type="unmapped"),
    ]
    sections = _group_by_section(items)
    assert sum(len(group) for _, group in sections) == len(items)


# --- markdown rendering --------------------------------------------------


def test_every_entry_links_to_the_publisher() -> None:
    """ADR-009: evidence resolves to the original, never a local copy."""
    markdown = render_markdown(TITLE, "总述", _group_by_section([item(url="https://openai.com/x")]))
    assert "(https://openai.com/x)" in markdown


def test_report_carries_an_ai_disclaimer() -> None:
    markdown = render_markdown(TITLE, "总述", _group_by_section([item()]))
    assert "AI" in markdown
    assert "原文为准" in markdown


def test_summary_appears_before_sections() -> None:
    markdown = render_markdown(TITLE, "今日总述", _group_by_section([item()]))
    assert markdown.index("今日总述") < markdown.index("## 模型发布")


def test_render_survives_missing_summary() -> None:
    markdown = render_markdown(TITLE, "", _group_by_section([item(summary=None)]))
    assert TITLE in markdown


# --- token accounting ----------------------------------------------------


def test_usage_accumulates_across_attempts() -> None:
    """A repair turn is billed too, so both attempts must be counted."""
    usage = TokenUsage()
    usage.add({"prompt_tokens": 100, "completion_tokens": 20}, elapsed_ms=500)
    usage.add({"prompt_tokens": 150, "completion_tokens": 30}, elapsed_ms=400)

    assert usage.prompt_tokens == 250
    assert usage.completion_tokens == 50
    assert usage.attempts == 2
    assert usage.latency_ms == 900


def test_usage_records_a_failed_attempt_with_no_payload() -> None:
    """A transport failure still consumed an attempt and wall time."""
    usage = TokenUsage()
    usage.add(None, elapsed_ms=250)

    assert usage.attempts == 1
    assert usage.latency_ms == 250
    assert usage.prompt_tokens == 0


def test_cached_tokens_tracked_separately() -> None:
    """Providers bill cached prompt tokens differently."""
    usage = TokenUsage()
    usage.add(
        {"prompt_tokens": 200, "completion_tokens": 40, "prompt_cache_hit_tokens": 120},
        elapsed_ms=300,
    )
    assert usage.cached_tokens == 120


# --- summarize ------------------------------------------------------------


def _client(handler) -> LlmClient:
    return LlmClient(
        LlmConfig(base_url="https://llm.example", api_key="k", model="m", max_attempts=1),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_summarize_returns_prose_without_json_mode() -> None:
    """Prose calls must not set response_format, or the model returns JSON."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as json_module

        seen.update(json_module.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "今日总述。"}}], "usage": {}}
        )

    async with _client(handler) as client:
        text, usage = await client.summarize(system_prompt="s", user_prompt="u")

    assert text == "今日总述。"
    assert "response_format" not in seen
    assert usage.attempts == 1


async def test_summarize_can_enforce_a_json_transport_contract() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as json_module

        seen.update(json_module.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"answer_markdown":"答案"}'}}]}
        )

    async with _client(handler) as client:
        await client.summarize(system_prompt="return json", user_prompt="u", json_mode=True)

    assert seen["response_format"] == {"type": "json_object"}


async def test_stream_summarize_can_enforce_a_json_transport_contract() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as json_module

        seen.update(json_module.loads(request.content))
        frame = 'data: {"choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=frame, headers={"content-type": "text/event-stream"})

    usage = TokenUsage()
    async with _client(handler) as client:
        pieces = [
            piece
            async for piece in client.stream_summarize(
                system_prompt="return json", user_prompt="u", usage=usage, json_mode=True
            )
        ]

    assert pieces == ["{}"]
    assert seen["response_format"] == {"type": "json_object"}


def test_rag_generation_enables_json_mode_for_both_paths() -> None:
    import inspect

    from ahr.rag.service import _generate

    assert inspect.getsource(_generate).count("json_mode=True") == 2


async def test_summarize_propagates_provider_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    async with _client(handler) as client:
        with pytest.raises(LlmUnavailableError):
            await client.summarize(system_prompt="s", user_prompt="u")


# --- period ranges --------------------------------------------------------


def test_daily_range_is_a_single_day() -> None:
    start, end, _ = _period_range("daily", "2026-08-01")
    assert start == end == date(2026, 8, 1)


def test_weekly_range_spans_seven_days_from_monday() -> None:
    start, end, _ = _period_range("weekly", "2026-W31")
    assert (end - start).days == 6
    assert start.weekday() == 0


def test_monthly_range_covers_the_whole_month() -> None:
    start, end, _ = _period_range("monthly", "2026-08")
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 31)


def test_december_rolls_into_the_next_year() -> None:
    """The only wrap case; getting it wrong would truncate December."""
    start, end, _ = _period_range("monthly", "2026-12")
    assert start == date(2026, 12, 1)
    assert end == date(2026, 12, 31)


def test_february_length_follows_the_calendar() -> None:
    assert _period_range("monthly", "2026-02")[1] == date(2026, 2, 28)
    assert _period_range("monthly", "2028-02")[1] == date(2028, 2, 29)


def test_unsupported_period_is_rejected() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError):
        _period_range("quarterly", "2026-Q1")


# --- persistence ----------------------------------------------------------


class _RecordingCursor:
    """Cursor stub that records statements instead of executing them.

    Enough to check the shape of the SQL and its parameters without a database,
    which keeps this test in the offline suite (AHR-QSO-700 §1).
    """

    def __init__(self, calls: list[tuple[str, tuple[object, ...]]]) -> None:
        self.calls = calls

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.calls.append((sql, params))

    def fetchone(self) -> tuple[uuid.UUID]:
        return (uuid.uuid4(),)


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.calls)

    def commit(self) -> None:
        return None


def _saved_insert(period: str, key: str) -> tuple[str, tuple[object, ...]]:
    from ahr.processing.report import DailyReport, save_report

    report = DailyReport(
        report_date=date(2026, 8, 1),
        period_type=period,
        period_key=key,
        title=f"标题 · {key}",
        summary="总述",
        body_markdown="# 标题",
        items=[item()],
        model_name="deepseek-chat",
    )
    connection = _RecordingConnection()
    save_report(connection, report)
    return next(call for call in connection.calls if "INSERT INTO report " in call[0])


@pytest.mark.parametrize(
    ("period", "key"),
    [("daily", "2026-08-01"), ("weekly", "2026-W31"), ("monthly", "2026-08")],
)
def test_insert_placeholders_match_parameters(period: str, key: str) -> None:
    """A hardcoded 'daily' literal left one fewer placeholder than parameters.

    psycopg only raises at execution time, so nothing caught it until a report
    was actually generated against a live database.
    """
    sql, params = _saved_insert(period, key)
    assert sql.count("%s") == len(params)


@pytest.mark.parametrize(
    ("period", "key"),
    [("daily", "2026-08-01"), ("weekly", "2026-W31"), ("monthly", "2026-08")],
)
def test_period_type_is_stored_not_assumed(period: str, key: str) -> None:
    """Every period must round-trip; a literal would file them all as daily."""
    _, params = _saved_insert(period, key)
    assert period in params
    assert key in params

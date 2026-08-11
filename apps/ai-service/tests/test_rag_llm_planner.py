"""The self-query planner, and the floor it must never fall below (Phase B-3).

The regex planner is right most of the time and wrong silently: `query_type`
decides whether the window filters the channels, which `source_fit` row applies
and whether `temporal_fit` runs, and none of those raise when the type is wrong.
Measured on ten live questions, three were misclassified.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime

import pytest

from ahr.processing.llm import LlmUnavailableError
from ahr.rag import llm_planner
from ahr.rag.llm_planner import _parse, plan_with_llm

ASKED = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


class _Llm:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls = 0

    async def summarize(self, *, system_prompt: str, user_prompt: str) -> tuple[str, object]:
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, object()


async def test_it_classifies_what_the_regex_planner_missed() -> None:
    """The live miss: 「发布顺序」 is a timeline and fell through to explainer."""
    llm = _Llm(
        '{"query_type": "timeline", "time_from": null, "time_to": null, "entities": ["Qwen"]}'
    )
    plan, from_model = await plan_with_llm(llm, "Qwen 系列模型的发布顺序是怎样的？", asked_at=ASKED)

    assert from_model is True
    assert plan.query_type == "timeline"
    assert plan.freshness_required is True


async def test_a_null_window_means_no_window_not_fall_back() -> None:
    """Otherwise the model can never correct the regex's habit of putting a
    seven-day window on an explainer, which is half of why it is here."""
    llm = _Llm('{"query_type": "explainer", "time_from": null, "time_to": null, "entities": []}')
    plan, _ = await plan_with_llm(llm, "最近的 MoE 路由是怎么工作的？", asked_at=ASKED)

    assert plan.time_range is None, "regex would have resolved 最近 to seven days"


async def test_dates_become_a_range_that_covers_the_last_day() -> None:
    """Shared with the reader's date picker: an off-by-one here is invisible in
    the chip and changes which documents are retrievable."""
    llm = _Llm(
        '{"query_type": "recent_updates", "time_from": "2026-08-02",'
        ' "time_to": "2026-08-08", "entities": []}'
    )
    plan, _ = await plan_with_llm(llm, "上周有什么动态？", asked_at=ASKED)

    assert plan.time_range is not None
    assert plan.time_range.start.date() == date(2026, 8, 2)
    # End-exclusive at the next midnight, so 08-08 is covered in full.
    assert plan.time_range.end.date() == date(2026, 8, 9)


async def test_a_provider_outage_costs_precision_not_the_answer() -> None:
    """A planner sits on the critical path of every question."""
    llm = _Llm(LlmUnavailableError("timeout"))
    plan, from_model = await plan_with_llm(llm, "最近有什么动态？", asked_at=ASKED)

    assert from_model is False
    assert plan.query_type == "recent_updates"
    assert plan.time_range is not None


@pytest.mark.parametrize(
    "reply",
    [
        "not json at all",
        '{"query_type": "recent-updates", "time_from": null, "time_to": null}',
        '{"query_type": "timeline", "time_from": "2026-08-09", "time_to": "2026-08-02"}',
        '{"query_type": "timeline", "time_from": "not-a-date", "time_to": "2026-08-02"}',
        '["a", "list"]',
    ],
)
async def test_unusable_output_falls_back_rather_than_being_coerced(reply: str) -> None:
    """A `query_type` outside the six is not a near-miss to round off — it would
    silently select the wrong `source_fit` row, and a correct planner is right
    there."""
    plan, from_model = await plan_with_llm(_Llm(reply), "最近有什么动态？", asked_at=ASKED)

    assert from_model is False
    assert plan.query_type in {
        "recent_updates",
        "timeline",
        "comparison",
        "fact_check",
        "explainer",
        "recommendation",
    }


def test_a_fenced_reply_is_still_read() -> None:
    parsed = _parse(
        '```json\n{"query_type": "fact_check", "time_from": null,'
        ' "time_to": null, "entities": ["MXFP4"]}\n```'
    )
    assert parsed is not None
    assert parsed.query_type == "fact_check"
    assert parsed.entities == ("MXFP4",)


def test_it_is_not_enabled_by_default() -> None:
    """It costs a model round trip per question and cannot yet be compared
    against the planner it would replace — the golden set has no
    `expected_query_type`. Shipping it on because it is more sophisticated is
    the move the evaluation discipline exists to prevent.
    """
    from ahr.rag import service

    assert "plan_with_llm" not in inspect.getsource(service.answer_question)


def test_disagreements_reports_differences_and_nothing_else() -> None:
    """It produces candidates for a human to adjudicate. Deriving the expected
    value from either planner would measure nothing."""
    source = inspect.getsource(llm_planner.disagreements)
    assert "if same_type and same_window:" in source
    assert "continue" in source

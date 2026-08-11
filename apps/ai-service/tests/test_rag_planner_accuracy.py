"""Planner accuracy, the §8 gate that had never been measured.

The gate was not failing — it was unjudgeable, which reads as a gate nobody has
to satisfy. What is pinned here is that the harness cannot produce a
comfortable number: unannotated questions never count as correct, and the
coverage travels with the score.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ahr.rag.eval.golden import NO_WINDOW, GoldenQuestion, GoldenSet, GoldenSetError
from ahr.rag.eval.golden import _parse_question as parse_question
from ahr.rag.eval.planner_accuracy import run_planner_eval, score_question, summarise

SHANGHAI = ZoneInfo("Asia/Shanghai")
ASKED = datetime(2026, 8, 3, 23, 59, tzinfo=SHANGHAI)


def _question(question: str, **kwargs: object) -> GoldenQuestion:
    return GoldenQuestion(
        id=kwargs.pop("id", "RAG-GOLD-TEST"),  # type: ignore[arg-type]
        category=kwargs.pop("category", "recent_updates"),  # type: ignore[arg-type]
        question=question,
        asked_at=ASKED,
        answerable=True,
        **kwargs,  # type: ignore[arg-type]
    )


def test_an_unannotated_question_is_not_scored_at_all() -> None:
    """ "Not measured" must never collapse into "correct" — that is how an
    unjudgeable gate turns into a passing one."""
    result = score_question(_question("llama.cpp 最近发布了哪些版本？"))

    assert result.query_type_correct is None
    assert result.time_correct is None
    assert result.entities_correct is None
    # The prediction is still recorded, so annotating later is a diff not a rerun.
    assert result.predicted_query_type == "recent_updates"


def test_the_score_carries_its_denominator() -> None:
    """1.00 over three questions is not a passing gate, and the summary must
    make that impossible to read as one."""
    results = [
        score_question(_question("最近有什么新模型？", expected_query_type="recent_updates")),
        score_question(_question("介绍一下 MoE 路由的原理")),
    ]
    summary = summarise(results, total_questions=90)["overall"]

    assert summary["query_type_accuracy"] == 1.0
    assert summary["query_type_scored"] == 1
    assert summary["annotated"] == 1
    assert summary["questions"] == 90
    assert summary["annotation_coverage"] == round(1 / 90, 4)


def test_a_wrong_classification_is_caught_and_explained() -> None:
    result = score_question(_question("为什么 MoE 会省算力？", expected_query_type="comparison"))

    assert result.query_type_correct is False
    assert result.predicted_query_type == "explainer"
    assert any("分类" in note for note in result.notes)


def test_a_half_open_window_is_compared_on_the_days_it_covers() -> None:
    """ "上周" ends at next Monday 00:00, which covers through Sunday.

    Comparing the raw end date would mark a correct planner wrong for an
    off-by-one in the comparison rather than in the thing being compared.
    """
    result = score_question(
        _question("上周发布了什么？", expected_time=(date(2026, 7, 27), date(2026, 8, 2)))
    )

    assert result.time_correct is True, result.notes


def test_no_window_is_an_expectation_not_a_missing_annotation() -> None:
    """An explainer should resolve no time range at all. That is a real thing to
    require, and the opposite of "nobody annotated this"."""
    explainer = score_question(_question("MoE 路由是怎么工作的？", expected_time=NO_WINDOW))
    assert explainer.time_correct is True

    timed = score_question(_question("最近有什么动态？", expected_time=NO_WINDOW))
    assert timed.time_correct is False
    assert any("时间窗" in note for note in timed.notes)


def test_a_default_seven_day_window_lands_where_section_3_says() -> None:
    """ "最近" without a span is 7 days ending at the question's own instant."""
    end = ASKED.date()
    result = score_question(
        _question("最近 Cloudflare 有什么动作？", expected_time=(end - timedelta(days=7), end))
    )

    assert result.time_correct is True, result.notes


def test_an_entity_the_question_never_names_is_flagged() -> None:
    result = score_question(_question("最近有什么新模型？", expected_entities=("Cloudflare",)))

    assert result.entities_correct is False
    assert any("实体" in note for note in result.notes)


def test_the_run_exits_loudly_when_nothing_is_annotated() -> None:
    """An empty run must not look like a clean pass."""
    golden = GoldenSet(questions=(_question("最近有什么动态？"),), source_files=("x.yaml",))
    payload = run_planner_eval(golden)

    assert payload["summary"]["overall"]["annotated"] == 0
    assert payload["summary"]["overall"]["query_type_accuracy"] is None
    assert payload["mistakes"] == []


def test_the_run_lists_every_disagreement_not_just_a_rate() -> None:
    """A rate says 8% are wrong; only the rows say which, and that decides
    whether the fix is a regex or a rethink."""
    golden = GoldenSet(
        questions=(
            _question("为什么 MoE 省算力？", id="a", expected_query_type="comparison"),
            _question("最近有什么动态？", id="b", expected_query_type="recent_updates"),
        ),
        source_files=("x.yaml",),
    )
    payload = run_planner_eval(golden)

    assert payload["summary"]["overall"]["query_type_accuracy"] == 0.5
    assert [m["question_id"] for m in payload["mistakes"]] == ["a"]


# --- annotation parsing ---------------------------------------------------


def _raw(**extra: object) -> dict[str, object]:
    return {
        "id": "RAG-GOLD-001",
        "question": "最近有什么动态？",
        "asked_at": ASKED,
        "answerable": True,
        "relevant_items": [{"id": "11111111-1111-1111-1111-111111111111", "grade": 2}],
        **extra,
    }


def test_an_unknown_query_type_fails_loudly() -> None:
    """A typo would otherwise be scored as a permanent planner failure."""
    from pathlib import Path

    with pytest.raises(GoldenSetError, match="expected_query_type"):
        parse_question(_raw(expected_query_type="recent-updates"), "recent_updates", Path("x.yaml"))


def test_expected_time_accepts_dates_and_the_no_window_sentinel() -> None:
    from pathlib import Path

    parsed = parse_question(
        _raw(expected_time={"from": "2026-07-27", "to": "2026-08-02"}),
        "recent_updates",
        Path("x.yaml"),
    )
    assert parsed.expected_time == (date(2026, 7, 27), date(2026, 8, 2))

    sentinel = parse_question(_raw(expected_time=NO_WINDOW), "recent_updates", Path("x.yaml"))
    assert sentinel.expected_time == NO_WINDOW


def test_a_backwards_window_is_rejected() -> None:
    from pathlib import Path

    with pytest.raises(GoldenSetError, match="before"):
        parse_question(
            _raw(expected_time={"from": "2026-08-02", "to": "2026-07-27"}),
            "recent_updates",
            Path("x.yaml"),
        )

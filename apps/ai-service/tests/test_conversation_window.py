"""A conversation keeps the time range it announced.

Turn 1 「最近 anthropic 有什么动态」 resolved 08-22 至 08-29 and said so on the
page. Turn 3 「那安全漏洞呢」 carried its subject forward — that is what the
rewriter is for — and carried no time at all, so the planner resolved nothing
and retrieval searched the whole corpus while the heading above it still
announced one week. The reader was shown one range and given results from
another, with nothing marking the difference.

The range now travels with the transcript, on the same terms as the cited
titles beside it: both are facts this system recorded, never sentences the
model wrote.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime

from ahr.rag.conversation import Turn
from ahr.rag.planner import plan
from ahr.rag.service import _latest_window, _window_of

ASKED = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
WEEK = (date(2026, 8, 22), date(2026, 8, 29))


def _turn(window: tuple[str, str] | None) -> Turn:
    return Turn(question="q", cited_titles=(), window=window)


# --- what the conversation contributes ------------------------------------


def test_the_newest_resolved_window_wins() -> None:
    """A follow-up that widens the range sets the scope for the turns after it.
    Taking the oldest would pin a conversation to its opening question forever,
    so 「那上个月呢」 would be honoured once and then quietly discarded."""
    turns = [_turn(("2026-08-01", "2026-08-07")), _turn(("2026-08-22", "2026-08-29"))]
    assert _latest_window(turns) == WEEK


def test_a_turn_that_resolved_no_window_is_skipped_not_treated_as_all_time() -> None:
    """Otherwise one undated follow-up would erase the conversation's scope for
    every turn after it — the same defect, one turn later."""
    turns = [_turn(("2026-08-22", "2026-08-29")), _turn(None)]
    assert _latest_window(turns) == WEEK


def test_a_malformed_stored_range_does_not_fail_the_answer() -> None:
    assert _latest_window([_turn(("not-a-date", "also-not"))]) is None
    assert _latest_window([]) is None


def test_the_window_round_trips_through_the_plan() -> None:
    resolved = plan("最近一周有什么动态", asked_at=ASKED)
    answer = type("A", (), {"plan": resolved})()
    stored = _window_of(answer)  # type: ignore[arg-type]
    assert stored is not None
    assert _latest_window([_turn(stored)]) is not None


# --- where it ranks -------------------------------------------------------


def test_a_time_word_in_the_follow_up_beats_the_inherited_range() -> None:
    """The conversation says what the reader is looking at; the sentence they
    just typed says what they are asking for. The sentence wins."""
    result = plan("上个月发布了什么", asked_at=ASKED, inherited_window=WEEK)
    assert result.time_range is not None
    assert result.time_range.start.date() < date(2026, 8, 22)


def test_the_readers_own_range_beats_both() -> None:
    override = (date(2026, 7, 1), date(2026, 7, 31))
    result = plan("有什么动态", asked_at=ASKED, window_override=override, inherited_window=WEEK)
    assert result.time_range is not None
    assert result.time_range.start.date() == date(2026, 7, 1)


def test_an_undated_follow_up_inherits_instead_of_widening_to_the_default() -> None:
    """`recent_updates` with no time word falls back to 30 days. A conversation
    that already settled on one week should not have its third turn silently
    widened to a month."""
    result = plan("那安全漏洞呢", asked_at=ASKED, inherited_window=WEEK)
    assert result.time_range is not None
    assert result.time_range.start.date() == date(2026, 8, 22)


def test_the_inheritance_is_visible_rather_than_silent() -> None:
    """The whole defect was a range applied without being stated. A label and a
    note are what make the third turn's scope checkable by the reader."""
    result = plan("那安全漏洞呢", asked_at=ASKED, inherited_window=WEEK)
    assert result.time_range is not None
    assert "沿用对话" in result.time_range.label
    assert any("沿用" in note for note in result.notes)


def test_inheriting_does_not_promote_the_range_to_a_hard_filter() -> None:
    """A range the reader typed is a request to filter by it. A range carried
    over from two turns ago is weaker evidence than that, and forcing it would
    make a follow-up unanswerable from anything published a day later."""
    inherited = plan("那安全漏洞呢", asked_at=ASKED, inherited_window=WEEK)
    typed = plan("那安全漏洞呢", asked_at=ASKED, window_override=WEEK)
    assert typed.freshness_required
    assert inherited.freshness_required == plan("那安全漏洞呢", asked_at=ASKED).freshness_required


def test_the_first_turn_of_a_thread_inherits_nothing() -> None:
    source = inspect.getsource(inspect.getmodule(_latest_window).answer_question)  # type: ignore[union-attr]
    # Guarded by the conversation id, so a fresh thread cannot pick up a range
    # from whatever happened to be in the caller's variables.
    assert "inherited_window = _latest_window(turns)" in source
    assert "if conversation_id:" in source

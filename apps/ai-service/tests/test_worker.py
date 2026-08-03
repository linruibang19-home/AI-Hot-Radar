"""Downstream pipeline worker.

The worker spends money (enrichment, reasons and reports are all LLM calls) and
writes to shared tables, so the parts worth testing offline are the guards: what
it refuses to redo, and what order it runs in.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from ahr.processing.worker import (
    ADVISORY_LOCK_KEY,
    _period_keys,
    _report_is_stale,
    _try_lock,
)


class _Cursor:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = answers
        self.queries: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.queries.append(sql)

    def fetchone(self) -> Any:
        return self.answers.pop(0)


class _Connection:
    def __init__(self, answers: list[Any]) -> None:
        self.cursor_obj = _Cursor(answers)

    def cursor(self) -> _Cursor:
        return self.cursor_obj


# --- report freshness -----------------------------------------------------


def test_missing_report_is_stale() -> None:
    """Nothing generated yet, so there is something to do."""
    assert _report_is_stale(_Connection([None]), "daily", "2026-08-02") is True


def test_report_older_than_the_newest_selection_is_stale() -> None:
    generated = datetime(2026, 8, 2, 10, 0)
    newest_selection = datetime(2026, 8, 2, 18, 0)
    assert _report_is_stale(_Connection([(generated,), (newest_selection,)]), "daily", "x") is True


def test_report_newer_than_every_selection_is_left_alone() -> None:
    """A fixed interval would otherwise pay for an identical digest every tick."""
    generated = datetime(2026, 8, 2, 18, 0)
    newest_selection = datetime(2026, 8, 2, 10, 0)
    assert _report_is_stale(_Connection([(generated,), (newest_selection,)]), "daily", "x") is False


def test_no_selections_at_all_is_not_stale() -> None:
    """An empty shortlist must not trigger an endless regeneration loop."""
    generated = datetime(2026, 8, 2, 18, 0)
    assert _report_is_stale(_Connection([(generated,), (None,)]), "daily", "x") is False


# --- period selection -----------------------------------------------------


def test_daily_report_covers_yesterday_not_today() -> None:
    """A report for a day still in progress would be rewritten all day and be
    wrong until midnight."""
    keys = dict(_period_keys(date(2026, 8, 3)))
    assert keys["daily"] == "2026-08-02"


def test_weekly_and_monthly_cover_the_period_in_progress() -> None:
    """These are explicitly running summaries; a reader looking at 本周 during
    the week expects the week so far, not an empty page."""
    keys = dict(_period_keys(date(2026, 8, 3)))
    assert keys["monthly"] == "2026-08"
    assert keys["weekly"].startswith("2026-W")


def test_daily_key_rolls_across_a_month_boundary() -> None:
    assert dict(_period_keys(date(2026, 8, 1)))["daily"] == "2026-07-31"


def test_daily_key_rolls_across_a_year_boundary() -> None:
    assert dict(_period_keys(date(2026, 1, 1)))["daily"] == "2025-12-31"


def test_weekly_key_uses_iso_week_numbering() -> None:
    """ISO weeks so the boundary is unambiguous; 2026-01-01 falls in week 1."""
    keys = dict(_period_keys(date(2026, 1, 5)))
    year, week = keys["weekly"].split("-W")
    assert 1 <= int(week) <= 53
    assert len(week) == 2


def test_all_three_periods_are_covered() -> None:
    assert {p for p, _ in _period_keys(date(2026, 8, 3))} == {"daily", "weekly", "monthly"}


# --- concurrency ----------------------------------------------------------


def test_lock_is_taken_when_free() -> None:
    assert _try_lock(_Connection([(True,)])) is True


def test_lock_refused_when_a_pass_is_already_running() -> None:
    """A pass can outlast its interval — enriching a backlog takes minutes — and
    two overlapping passes would double-charge the model for the same items."""
    assert _try_lock(_Connection([(False,)])) is False


def test_lock_key_is_stable() -> None:
    """Changing this between deploys would let two versions run concurrently."""
    assert ADVISORY_LOCK_KEY == 0x41485231


# --- stage ordering -------------------------------------------------------


def test_clustering_runs_before_selection() -> None:
    """select-v2 reads story.independent_source_count, so selecting first would
    score every item as uncorroborated and silently undo the M3 fix."""
    import inspect

    from ahr.processing import worker

    source = inspect.getsource(worker.run_once)
    assert source.index("recluster(") < source.index("select_for_days(")


def test_reasons_run_after_selection() -> None:
    """Reasons are written per selection_record row, so there is nothing to
    write until selection has run."""
    import inspect

    from ahr.processing import worker

    source = inspect.getsource(worker.run_once)
    assert source.index("select_for_days(") < source.index("backfill_reasons(")


@pytest.mark.parametrize("delta_hours", [-1, 0, 1])
def test_staleness_boundary_is_strict(delta_hours: int) -> None:
    """Equal timestamps count as fresh: regenerating on a tie would loop."""
    generated = datetime(2026, 8, 2, 12, 0)
    newest = generated + timedelta(hours=delta_hours)
    expected = delta_hours > 0
    assert _report_is_stale(_Connection([(generated,), (newest,)]), "daily", "x") is expected

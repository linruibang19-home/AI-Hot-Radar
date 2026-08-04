"""Downstream pipeline worker.

The worker spends money (enrichment, reasons and reports are all LLM calls) and
writes to shared tables, so the parts worth testing offline are the guards: what
it refuses to redo, and what order it runs in.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from ahr.processing.worker import (
    ADVISORY_LOCK_KEY,
    DAILY_CUTOFF_HOUR,
    _period_keys,
    _report_is_stale,
    _try_lock,
)
from ahr.rag.planner import DISPLAY_TIMEZONE


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


def _at(year: int, month: int, day: int, hour: int) -> datetime:
    """A wall-clock moment in the display timezone."""
    return datetime(year, month, day, hour, 0, tzinfo=DISPLAY_TIMEZONE)


def test_todays_daily_is_withheld_until_the_evening_cutoff() -> None:
    """A digest of a day still running is a digest of half a day.

    The pipeline passes every 15 minutes, so today's report was rewritten all
    day on whatever had arrived: at noon it summarised a morning and called it
    the day. Before the cutoff the site shows yesterday's, which is complete.
    """
    daily = [key for period, key in _period_keys(_at(2026, 8, 3, 12)) if period == "daily"]
    assert daily == ["2026-08-02"]


def test_todays_daily_appears_once_the_cutoff_passes() -> None:
    daily = [
        key for period, key in _period_keys(_at(2026, 8, 3, DAILY_CUTOFF_HOUR)) if period == "daily"
    ]
    assert daily == ["2026-08-03", "2026-08-02"]


def test_the_day_is_the_local_day_not_the_utc_day() -> None:
    """02:00 Beijing is 18:00 UTC the previous day.

    Deriving the date from `datetime.now(UTC)` refreshed the wrong day's digest
    for the whole Beijing morning.
    """
    keys = _period_keys(_at(2026, 8, 3, 2))
    daily = [key for period, key in keys if period == "daily"]
    assert daily == ["2026-08-02"]


def test_weekly_and_monthly_cover_the_period_in_progress() -> None:
    """These are explicitly running summaries; a reader looking at 本周 during
    the week expects the week so far, not an empty page."""
    keys = dict((p, k) for p, k in _period_keys(_at(2026, 8, 3, 22)))
    assert keys["monthly"] == "2026-08"
    assert keys["weekly"].startswith("2026-W")


def test_daily_key_rolls_across_a_month_boundary() -> None:
    daily = [key for period, key in _period_keys(_at(2026, 8, 1, 22)) if period == "daily"]
    assert daily == ["2026-08-01", "2026-07-31"]


def test_daily_key_rolls_across_a_year_boundary() -> None:
    daily = [key for period, key in _period_keys(_at(2026, 1, 1, 22)) if period == "daily"]
    assert daily == ["2026-01-01", "2025-12-31"]


def test_every_period_key_pair_is_distinct() -> None:
    """Duplicates would make the pass regenerate the same report twice."""
    keys = _period_keys(_at(2026, 8, 3, 22))
    assert len(keys) == len(set(keys))


def test_weekly_key_uses_iso_week_numbering() -> None:
    """ISO weeks so the boundary is unambiguous; 2026-01-01 falls in week 1."""
    keys = dict(_period_keys(_at(2026, 1, 5, 22)))
    year, week = keys["weekly"].split("-W")
    assert 1 <= int(week) <= 53
    assert len(week) == 2


def test_all_three_periods_are_covered() -> None:
    assert {p for p, _ in _period_keys(_at(2026, 8, 3, 22))} == {"daily", "weekly", "monthly"}


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

"""Publication-date sanity tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ahr.ingestion.repository import sanitize_published_at

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def test_normal_date_is_kept() -> None:
    stamp = NOW - timedelta(days=1)
    assert sanitize_published_at(stamp, now=NOW) == stamp


def test_small_clock_skew_is_tolerated() -> None:
    """Publishers are minutes ahead of us, not hours."""
    stamp = NOW + timedelta(minutes=30)
    assert sanitize_published_at(stamp, now=NOW) == stamp


def test_far_future_date_is_discarded() -> None:
    """Regression: OpenAlex returned 2045 dates that pinned the hot list."""
    assert sanitize_published_at(datetime(2045, 12, 10, tzinfo=UTC), now=NOW) is None


def test_absurdly_old_date_is_discarded() -> None:
    assert sanitize_published_at(datetime(1970, 1, 1, tzinfo=UTC), now=NOW) is None


def test_none_stays_none() -> None:
    assert sanitize_published_at(None, now=NOW) is None


def test_naive_datetime_is_treated_as_utc() -> None:
    naive = datetime(2026, 8, 1, 12, 0)
    assert sanitize_published_at(naive, now=NOW) == naive.replace(tzinfo=UTC)

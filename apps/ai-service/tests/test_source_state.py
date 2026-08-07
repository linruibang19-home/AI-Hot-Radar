"""A source's state describes the source, not one poll of it.

Five sources sat in DEGRADED and thirteen in PROBING while every one of them
had `consecutive_failures = 0`, no error code, and a successful fetch minutes
earlier. The admin page showed "DEGRADED · 100% 全文率 · 最近成功 08-04 23:45",
which is a contradiction on its face.

The cause was that the verdict came from the current run's yield: two or more
accepted documents meant ACTIVE, exactly one meant DEGRADED. The scheduler polls
every two minutes, so a healthy low-volume feed hits that branch constantly.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from ahr.ingestion.errors import (
    NotFoundError,
    RateLimitedError,
    SsrfBlockedError,
    TransientError,
)
from ahr.ingestion.health import next_state_after_failure
from ahr.ingestion.pipeline import _state_from_evidence, ingest_source
from ahr.ingestion.repository import record_source_failure


class _Cursor:
    def __init__(self, row: tuple[int, int] | None) -> None:
        self.row = row

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = ()) -> None:
        return None

    def fetchone(self) -> tuple[int, int] | None:
        return self.row


class _Connection:
    def __init__(self, row: tuple[int, int] | None) -> None:
        self.row = row

    def cursor(self) -> _Cursor:
        return _Cursor(self.row)


# --- the earned verdict ----------------------------------------------------


def test_a_source_that_cleared_the_gate_before_is_active() -> None:
    assert _state_from_evidence(_Connection((7, 0)), "s") == "ACTIVE"


def test_a_metadata_only_source_keeps_that_verdict() -> None:
    assert _state_from_evidence(_Connection((0, 3)), "s") == "METADATA_ONLY"


def test_a_source_with_no_evidence_yet_has_no_earned_verdict() -> None:
    """None means "undecided", and the caller turns that into PROBING — which
    is correct for a source that has genuinely never produced anything."""
    assert _state_from_evidence(_Connection((0, 0)), "s") is None
    assert _state_from_evidence(_Connection((1, 0)), "s") is None


# --- which branches consult it ---------------------------------------------


def test_a_single_accepted_document_is_not_a_degradation() -> None:
    """The defect, stated as the rule that was missing. One new article in a
    two-minute poll is an ordinary result for Langfuse Releases or The Verge AI,
    and all five DEGRADED sources looked exactly like this."""
    source = inspect.getsource(ingest_source)
    single = source.index("stats.fulltext_accepted == 1")
    branch = source[single : single + 320]

    assert "_state_from_evidence" in branch
    assert "DEGRADED" not in branch


def test_a_poll_of_nothing_but_already_stored_items_is_not_degradation() -> None:
    """The second half of the same defect. `The Verge AI` had 16 accepted
    documents, zero failures and still read DEGRADED, because the feed it was
    polled from held only articles already in the database. A feed polled more
    often than it publishes looks exactly like this."""
    source = inspect.getsource(ingest_source)

    # Rejection is the real signal and is the only thing that sets DEGRADED.
    guards = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("if ", "elif ", "else:")) and "result.state" not in line
    ]
    assert "elif stats.rejected:" in guards
    # The branch after it — items present, nothing rejected — falls back to the
    # earned verdict rather than judging the source on one quiet poll.
    fallback = source.split("elif stats.rejected:")[1]
    assert "_state_from_evidence" in fallback


def test_items_that_all_fail_the_gate_still_degrade() -> None:
    """The one branch that should judge the run: documents arrived and none
    passed. Consulting history there would hide a source that has started
    serving pages the extractor cannot read."""
    source = inspect.getsource(ingest_source)
    # Comments mention the word too, so look at assignments only.
    assignments = [
        line.strip()
        for line in source.splitlines()
        if "result.state =" in line and "DEGRADED" in line
    ]
    assert assignments == ['result.state = "DEGRADED"']


def test_a_quiet_poll_preserves_the_earned_verdict() -> None:
    source = inspect.getsource(ingest_source)
    empty = source.index("if not batch.items:")
    assert "_state_from_evidence" in source[empty : empty + 320]


# --- the failure ladder (AHR-SOURCE-900 §5) --------------------------------
#
# The same principle applied to the other direction. Quarantining on the first
# error put eighteen first-party sources — Anthropic, Hugging Face, arXiv, vLLM,
# the OpenAI SDK repos, 量子位, Simon Willison — into QUARANTINED at once, each
# with `consecutive_failures = 1` and a DNS error that had already cleared.


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _ladder(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "current_state": "ACTIVE",
        "error_code": "TRANSIENT",
        "retryable": True,
        "consecutive_failures": 0,
        "last_success_at": NOW - timedelta(minutes=10),
        "created_at": NOW - timedelta(days=30),
        "now": NOW,
    }
    kwargs.update(overrides)
    return next_state_after_failure(**kwargs)  # type: ignore[arg-type]


def test_one_transient_failure_does_not_change_the_verdict() -> None:
    """The defect, stated as the rule that was missing."""
    assert _ladder(consecutive_failures=0) == "ACTIVE"
    assert _ladder(consecutive_failures=1) == "ACTIVE"


def test_three_consecutive_failures_degrade() -> None:
    """§5: 连续 3 次失败 … 进入 DEGRADED. The third failure is the one that trips
    it, so the count *before* it is two."""
    assert _ladder(consecutive_failures=2) == "DEGRADED"


def test_a_day_of_continuous_failure_quarantines() -> None:
    """§5: 连续 24 小时失败进入 QUARANTINED."""
    assert (
        _ladder(consecutive_failures=8, last_success_at=NOW - timedelta(hours=25)) == "QUARANTINED"
    )


def test_an_old_success_alone_does_not_quarantine() -> None:
    """`last_success_at` is only a proxy for "failing since". A source polled
    every three hours that succeeded 25 hours ago and then fails once has not
    been failing for 24 hours — it has failed once. Reading the timestamp
    without the count would quarantine it on that single error."""
    assert _ladder(consecutive_failures=0, last_success_at=NOW - timedelta(hours=25)) == "ACTIVE"


def test_a_source_that_never_succeeded_ages_out_from_creation() -> None:
    """Otherwise a permanently broken entry sits in DEGRADED forever, because it
    has no success timestamp to age out."""
    assert (
        _ladder(consecutive_failures=5, last_success_at=None, created_at=NOW - timedelta(days=2))
        == "QUARANTINED"
    )
    assert (
        _ladder(
            consecutive_failures=5, last_success_at=None, created_at=NOW - timedelta(minutes=30)
        )
        == "DEGRADED"
    )


def test_unretryable_errors_still_quarantine_immediately() -> None:
    """A login wall, a 404 or an SSRF verdict will not resolve by being retried,
    and the ladder exists to protect sources that might recover — not to keep
    polling one that cannot."""
    for code in ("NOT_FOUND", "ACCESS_RESTRICTED", "SSRF_BLOCKED", "PARSE_FAILED"):
        assert _ladder(error_code=code, retryable=False) == "QUARANTINED"


def test_rate_limiting_keeps_its_own_state() -> None:
    """V003 decided this: quota exhaustion says nothing about source health, so
    it never enters the ladder in either direction."""
    assert _ladder(error_code="RATE_LIMITED", consecutive_failures=99) == "RATE_LIMITED"


def test_the_taxonomy_is_the_source_of_truth_for_retryability() -> None:
    """`errors.py` already fixes which codes may be retried (AHR-INGEST-1000
    §12). The pipeline must consume that decision rather than re-derive it from
    status codes, which is how DNS failures once ended up classified as SSRF."""
    assert TransientError("dns").retryable is True
    assert RateLimitedError("429").retryable is True
    assert NotFoundError("404").retryable is False
    assert SsrfBlockedError("private ip").retryable is False

    source = inspect.getsource(ingest_source)
    assert "retryable=exc.retryable" in source


class _FailureCursor:
    def __init__(self, row: tuple[object, ...] | None, log: list[tuple[str, object]]) -> None:
        self.row = row
        self.log = log

    def __enter__(self) -> _FailureCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = ()) -> None:
        self.log.append((sql, params))

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class _FailureConnection:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.row = row
        self.log: list[tuple[str, object]] = []

    def cursor(self) -> _FailureCursor:
        return _FailureCursor(self.row, self.log)


def test_recording_a_failure_writes_the_ladder_verdict() -> None:
    connection = _FailureConnection(
        ("ACTIVE", 0, NOW - timedelta(minutes=10), NOW - timedelta(days=30), NOW)
    )
    state = record_source_failure(
        connection,
        "huggingface-blog",
        error_code="TRANSIENT",
        error_detail="dns resolution failed",
        retryable=True,
    )

    assert state == "ACTIVE"
    # The error is still recorded, so the admin page can say "ACTIVE, last
    # attempt failed" instead of silently swallowing it.
    update = [sql for sql, _ in connection.log if "last_error_code" in sql]
    assert update and "consecutive_failures = consecutive_failures + 1" in update[0]


def test_the_row_is_locked_before_the_count_is_read() -> None:
    """Two workers polling the same source would otherwise both read the same
    count and each write a verdict derived from a stale number."""
    connection = _FailureConnection(("ACTIVE", 0, NOW, NOW, NOW))
    record_source_failure(connection, "s", error_code="TRANSIENT", error_detail="x", retryable=True)
    assert "FOR UPDATE" in connection.log[0][0]

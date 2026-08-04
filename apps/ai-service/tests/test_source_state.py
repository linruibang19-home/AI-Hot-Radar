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

from ahr.ingestion.pipeline import _state_from_evidence, ingest_source


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

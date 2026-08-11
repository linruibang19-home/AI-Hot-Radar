"""Bounding `outbox_event` without eating a future consumer's backlog.

The table has 1562 rows and zero consumers, so pruning it is safe *today*.
What these tests pin is the condition under which that stops being true.
"""

from __future__ import annotations

import inspect
from typing import Any

from ahr.ingestion import retention, scheduler


class _Cursor:
    def __init__(self, published_count: int) -> None:
        self.published_count = published_count
        self.statements: list[str] = []
        self.rowcount = 3

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = ()) -> None:
        self.statements.append(" ".join(sql.split()))

    def fetchone(self) -> tuple[int]:
        return (self.published_count,)


class _Connection:
    def __init__(self, published_count: int = 0) -> None:
        self.cur = _Cursor(published_count)
        self.committed = False

    def cursor(self) -> _Cursor:
        return self.cur

    def commit(self) -> None:
        self.committed = True


def _delete_statement(connection: _Connection) -> str:
    return next(s for s in connection.cur.statements if s.startswith("DELETE"))


# --- the rule changes the day a consumer exists ----------------------------


def test_with_no_consumer_old_rows_go_regardless_of_publication() -> None:
    """Nothing has ever read this table, so an unpublished row is debris rather
    than a pending delivery."""
    connection = _Connection(published_count=0)

    retention.prune_outbox(connection)

    statement = _delete_statement(connection)
    assert "created_at <" in statement
    assert "published_at IS NOT NULL" not in statement


def test_once_anything_is_published_only_published_rows_are_deleted() -> None:
    """The guard that matters. Without it, wiring up a reader would hand it a
    pruner that silently discards its backlog."""
    connection = _Connection(published_count=1)

    retention.prune_outbox(connection)

    statement = _delete_statement(connection)
    assert "published_at IS NOT NULL" in statement
    assert "published_at <" in statement


def test_the_publication_check_happens_before_the_delete() -> None:
    connection = _Connection(published_count=0)

    retention.prune_outbox(connection)

    kinds = [s.split()[0] for s in connection.cur.statements]
    assert kinds.index("SELECT") < kinds.index("DELETE")


def test_the_deletion_is_committed_and_counted() -> None:
    connection = _Connection()

    assert retention.prune_outbox(connection) == 3
    assert connection.committed


def test_the_window_is_long_enough_to_debug_a_week() -> None:
    assert retention.OUTBOX_RETENTION_DAYS >= 7


# --- it runs, and it cannot stop ingestion ---------------------------------


def test_the_scheduler_prunes_on_its_own_rather_than_needing_a_cron_entry() -> None:
    source = inspect.getsource(scheduler.run_forever)
    assert "prune_outbox" in source


def test_pruning_is_not_on_the_two_minute_path() -> None:
    """A DELETE over a growing table has no business running every tick."""
    assert scheduler.PRUNE_EVERY_TICKS >= 60


def test_a_failed_prune_does_not_stop_the_loop() -> None:
    """Housekeeping is the least important thing this process does; it must not
    be able to take ingestion down."""
    source = inspect.getsource(scheduler.run_forever)
    prune_at = source.index("prune_outbox")
    assert "except Exception" in source[prune_at:]

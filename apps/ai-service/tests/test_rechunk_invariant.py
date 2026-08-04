"""Every current revision keeps its chunks.

1.4% of the corpus was invisible to retrieval while every count looked healthy:
items had a body, a revision and an embedding model configured, but the chunks
belonged to a revision that had been superseded. The generation evaluation
surfaced it as a citation-precision failure — the answer cited a quantum
calibration tool for a question about NVFP4 — which is three layers away from
the cause.

Two things had to be true at once for that to happen, so both are pinned here.
"""

from __future__ import annotations

import inspect
from typing import Any

from ahr.processing.pipeline import (
    _unchunked_revisions,
    chunk_current_revisions,
    close_empty_bodies,
    process_pending,
)


class _Cursor:
    def __init__(self, rows: list[Any] | None = None, rowcount: int = 0) -> None:
        self.rows = rows or []
        self.rowcount = rowcount
        self.queries: list[str] = []
        self.params: list[Any] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = ()) -> None:
        self.queries.append(sql)
        self.params.append(params)

    def fetchall(self) -> list[Any]:
        return self.rows


class _Connection:
    def __init__(self, rows: list[Any] | None = None, rowcount: int = 0) -> None:
        self.cursor_obj = _Cursor(rows, rowcount)
        self.commits = 0

    def cursor(self) -> _Cursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1


# --- selection is by the invariant, not by enrichment state ----------------


def test_unchunked_query_does_not_filter_on_enrichment_state() -> None:
    """The whole defect. Chunking is a pure function of the body, but it only
    ran for items queued for the model, so an already-ENRICHED item that was
    re-crawled never got its new body split."""
    connection = _Connection([])
    _unchunked_revisions(connection, 10)

    sql = connection.cursor_obj.queries[0]
    assert "enrichment_state" not in sql


def test_unchunked_query_selects_revisions_missing_chunks() -> None:
    connection = _Connection([])
    _unchunked_revisions(connection, 10)

    sql = " ".join(connection.cursor_obj.queries[0].split())
    assert "NOT EXISTS" in sql
    assert "content_chunk" in sql
    # Must key on the *current* revision: chunks hanging off a superseded one
    # are exactly the state being repaired.
    assert "cc.content_revision_id = ci.current_revision_id" in sql


def test_unchunked_query_skips_known_duplicates() -> None:
    """A near-duplicate is never retrieved on its own, so splitting it would
    pay for index space that only competes with the original."""
    connection = _Connection([])
    _unchunked_revisions(connection, 10)

    assert "duplicate_of_id IS NULL" in connection.cursor_obj.queries[0]


def test_chunking_runs_before_enrichment_in_the_pass() -> None:
    """Ordering matters for cost, not correctness: enrichment can exhaust the
    limit or fail on a provider outage, and retrievability should not depend on
    a model being reachable."""
    source = inspect.getsource(process_pending)
    assert source.index("chunk_current_revisions(") < source.index("_pending_items(")


def test_enrichment_loop_no_longer_chunks() -> None:
    """Two code paths writing the same chunks would race on the DELETE and
    re-INSERT and double the work every pass."""
    source = inspect.getsource(process_pending)
    assert "chunk_revision(" not in source


# --- empty bodies are closed, not left pending forever ---------------------


def test_empty_bodies_are_closed_out_of_pending() -> None:
    """`_pending_items` requires a non-empty body, so these matched nothing and
    stayed PENDING permanently — a backlog that could never reach zero."""
    connection = _Connection(rowcount=8)
    assert close_empty_bodies(connection) == 8

    sql = " ".join(connection.cursor_obj.queries[0].split())
    assert "length(cr.body_text) = 0" in sql
    assert "SKIPPED" in sql


def test_closing_empty_bodies_only_touches_pending_rows() -> None:
    """An item already SKIPPED as a near-duplicate must keep that reason: it
    explains why the item is not shown, and 'no body text' does not."""
    connection = _Connection(rowcount=0)
    close_empty_bodies(connection)

    assert "ci.enrichment_state = 'PENDING'" in connection.cursor_obj.queries[0]


# --- the repair pass itself ------------------------------------------------


def test_chunking_pass_reports_what_it_wrote() -> None:
    connection = _Connection([])
    assert chunk_current_revisions(connection, 10) == (0, 0)
    # Committed even with nothing to do, so the pass never holds a transaction
    # open across the enrichment loop that follows.
    assert connection.commits == 1


# --- ingestion invalidates what it supersedes ------------------------------


def test_superseding_a_revision_reopens_the_item() -> None:
    """The source of new cases.

    A revision row is only written when the body hash changed, so by the time
    the pointer moves every derived artefact describes text nobody reads any
    more. Advancing `current_revision_id` while leaving the item ENRICHED is
    what made the stale state look healthy.
    """
    from ahr.ingestion import repository

    source = inspect.getsource(repository)
    move = source.index("SET current_revision_id = %s")
    window = source[move : move + 400]
    assert "enrichment_state" in window
    assert "PENDING" in window


def test_superseding_leaves_known_duplicates_alone() -> None:
    """Duplicates are excluded from processing by `duplicate_of_id`, so
    reopening one would park it in PENDING for good — the same trap in a new
    place."""
    from ahr.ingestion import repository

    source = inspect.getsource(repository)
    move = source.index("SET current_revision_id = %s")
    assert "duplicate_of_id IS NULL" in source[move : move + 400]

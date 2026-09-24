"""The windowless dense path ranks chunks before joining, and never approximates.

Measured 2026-09-24 on the production host: 11.5 s joined-then-sorted versus
0.9 s ranked-then-joined for the same 60 rows. These tests pin the part that
keeps the faster path exact — the fallback when filtering thins the list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ahr.rag.retrieval import DENSE_CANDIDATES, dense_search


class _Cursor:
    def __init__(self, answers: list[list[tuple[Any, ...]]], log: list[str]) -> None:
        self.answers = answers
        self.log = log

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.log.append(sql)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.answers.pop(0)


class _Connection:
    def __init__(self, *answers: list[tuple[Any, ...]]) -> None:
        self.answers = list(answers)
        self.log: list[str] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.answers, self.log)


def _rows(n: int) -> list[tuple[Any, ...]]:
    return [
        (f"chunk-{i}", f"item-{i}", 0.9 - i / 1000, "t", "s", "src", "primary") for i in range(n)
    ]


def test_enough_survivors_are_returned_without_the_joined_query() -> None:
    connection = _Connection(_rows(60))
    hits = dense_search(connection, [0.1] * 4, limit=60)
    assert [h.chunk_id for h in hits] == [f"chunk-{i}" for i in range(60)]
    assert len(connection.log) == 1
    assert "WITH candidate AS MATERIALIZED" in connection.log[0]


def test_too_few_survivors_fall_back_to_the_exact_joined_query() -> None:
    """Fewer than `limit` survivors means the candidate list cannot prove exactness."""
    connection = _Connection(_rows(59), _rows(60))
    hits = dense_search(connection, [0.1] * 4, limit=60)
    assert len(hits) == 60
    assert len(connection.log) == 2
    assert "WITH candidate" not in connection.log[1]


def test_a_window_keeps_the_filtered_query() -> None:
    """With a window the filter already shrinks the set; that path was 43 ms."""
    connection = _Connection(_rows(10))
    window = (datetime(2026, 9, 15, tzinfo=UTC), datetime(2026, 9, 22, tzinfo=UTC))
    dense_search(connection, [0.1] * 4, limit=60, window=window)
    assert len(connection.log) == 1
    assert "WITH candidate" not in connection.log[0]


def test_the_candidate_list_is_wider_than_the_answer() -> None:
    assert DENSE_CANDIDATES >= 6 * 60


def test_the_candidate_subquery_cannot_use_the_hnsw_index() -> None:
    """On production the planner picked the index here and got 40 approximate rows.

    `ORDER BY 3` over a bare `embedding <=> vector` is exactly what the HNSW
    index serves, and it caps results at `hnsw.ef_search`. The `+ 0` makes the
    expression unmatchable, which is what keeps this path exact.
    """
    connection = _Connection(_rows(60))
    dense_search(connection, [0.1] * 4, limit=60)
    assert "(ch.embedding <=> %s::vector) + 0" in connection.log[0]

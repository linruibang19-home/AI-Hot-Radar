"""The keyword channel takes the GIN index first and joins afterwards.

Production, 2026-09-24 (v0.1.30, 42k chunks): with the tsquery match inside the
join list, the planner estimated the item-revision join at 1 row where 7,521 came
back, and chose a nested loop that fetched every chunk of every revision to test
the match on it — 48,521 pages read, 13.4 s for 「MXFP4 量化是什么？」. Locally the
whole table is cached and the same query took 0.15 s, so no local run showed it.
"""

from __future__ import annotations

from typing import Any

import pytest

from ahr.rag import retrieval


class _Cursor:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.log.append(sql)

    def fetchone(self) -> tuple[Any, ...]:
        return (1000,)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _Connection:
    def __init__(self) -> None:
        self.log: list[str] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.log)


def _main_query(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(retrieval, "select_query_terms", lambda *a, **k: [("mxfp4", 205)])
    connection = _Connection()
    retrieval.sparse_search(connection, "MXFP4 量化是什么？")
    return connection.log[-1]


def test_the_match_is_materialised_before_any_join(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _main_query(monkeypatch)
    assert "matched AS MATERIALIZED" in sql
    match_at = sql.index("search_vector @@ to_tsquery('simple', %s)")
    assert match_at < sql.index("JOIN content_revision")


def test_the_joins_read_from_the_materialised_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Joining `content_chunk` again would hand the planner the old choice back."""
    sql = _main_query(monkeypatch)
    assert "FROM matched ch" in sql
    assert "JOIN content_chunk" not in sql

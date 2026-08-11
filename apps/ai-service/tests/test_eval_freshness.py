"""Keeping the measuring instrument honest.

The golden set was annotated against the corpus of 2026-08-03. Measured today,
602 of 1580 items arrived after that — the corpus is 62% larger than the one the
annotations describe. Nothing was checking that, and an evaluation set is only
an instrument for as long as its annotations still hold.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

from ahr.rag.eval import freshness


class _Cursor:
    """Answers each of the four queries by matching on its SQL."""

    def __init__(self, present: list[str], retrievable: list[str], corpus: int, since: int):
        self.present = present
        self.retrievable = retrievable
        self.corpus = corpus
        self.since = since
        self.rows: list[tuple[Any, ...]] = []
        self.scalar: tuple[Any, ...] = (0,)
        self.seen: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = ()) -> None:
        flat = " ".join(sql.split())
        self.seen.append(flat)
        if "content_chunk" in flat:
            self.rows = [(item,) for item in self.retrievable]
        elif "count(*) FROM content_item WHERE" in flat:
            self.scalar = (self.since,)
        elif "count(*) FROM content_item" in flat:
            self.scalar = (self.corpus,)
        else:
            self.rows = [(item,) for item in self.present]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def fetchone(self) -> tuple[Any, ...]:
        return self.scalar


class _Connection:
    def __init__(self, **kwargs: Any) -> None:
        self.cur = _Cursor(**kwargs)

    def cursor(self) -> _Cursor:
        return self.cur


class _Question:
    def __init__(self, qid: str, relevant: list[str]) -> None:
        self.id = qid
        self.relevant_ids = frozenset(relevant)
        self.asked_at = datetime(2026, 8, 3, tzinfo=UTC)


class _Golden:
    def __init__(self, questions: list[_Question]) -> None:
        self.questions = questions

    @property
    def item_ids(self) -> frozenset[str]:
        return frozenset(i for q in self.questions for i in q.relevant_ids)


def _run(present: list[str], retrievable: list[str], corpus: int = 100, since: int = 0):
    golden = _Golden([_Question("Q1", ["a", "b"]), _Question("Q2", ["c"])])
    return freshness.check(
        _Connection(present=present, retrievable=retrievable, corpus=corpus, since=since),
        golden,  # type: ignore[arg-type]
    )


# --- the two kinds of rot an id check can see -------------------------------


def test_a_healthy_set_reports_nothing_broken() -> None:
    result = _run(present=["a", "b", "c"], retrievable=["a", "b", "c"])

    assert result["missing"] == []
    assert result["unretrievable"] == []
    assert result["affectedQuestions"] == []


def test_a_deleted_annotation_target_is_reported() -> None:
    """Recall computed against a target that no longer exists drops for a reason
    that has nothing to do with retrieval."""
    result = _run(present=["a", "c"], retrievable=["a", "c"])

    assert result["missing"] == ["b"]
    assert result["affectedQuestions"] == ["Q1"]


def test_an_item_that_exists_but_cannot_be_retrieved_is_a_separate_finding() -> None:
    """The failure this project already shipped once: every counter healthy,
    content invisible to search because the chunks hung off a superseded
    revision."""
    result = _run(present=["a", "b", "c"], retrievable=["a", "b"])

    assert result["missing"] == []
    assert result["unretrievable"] == ["c"]
    assert result["affectedQuestions"] == ["Q2"]


def test_retrievability_is_judged_on_the_current_revision() -> None:
    source = inspect.getsource(freshness.check)
    assert "current_revision_id" in source
    assert "embedding IS NOT NULL" in source


# --- the kind it cannot ------------------------------------------------------


def test_corpus_growth_is_reported_even_when_every_id_still_resolves() -> None:
    """The rot no id check can see. A question asked on 08-03 about "本周动态"
    has a different correct answer today, and every annotated id is still fine.
    All this can do is say how much has changed and ask for a human."""
    result = _run(present=["a", "b", "c"], retrievable=["a", "b", "c"], corpus=160, since=60)

    assert result["missing"] == []
    assert result["corpusGrowth"] == 0.6
    assert result["reviewRecommended"] is True


def test_a_stable_corpus_does_not_ask_for_a_review() -> None:
    result = _run(present=["a", "b", "c"], retrievable=["a", "b", "c"], corpus=102, since=2)

    assert result["reviewRecommended"] is False


def test_the_review_threshold_is_not_quietly_raised() -> None:
    assert freshness.GROWTH_REVIEW_THRESHOLD <= 0.5

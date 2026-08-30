"""Rendering mined candidates into a sheet someone can actually annotate.

Two things here are load-bearing and neither is obvious from the output. The
document list comes from the retrieval trace rather than the citations, so an
annotator can contradict the pipeline instead of only confirming it. And a
document dated after the question is shown but cannot be graded, because the
evaluation clamps retrieval to the corpus as it stood at `asked_at` and would
never be able to retrieve it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ahr.rag.eval.golden import CATEGORIES
from ahr.rag.eval.worksheet import render, validate


class _Cursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: dict) -> None:
        self.sql = sql
        self.params = params

    def fetchall(self) -> list[tuple]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def cursor(self) -> _Cursor:
        return _Cursor(self._rows)


def _row(item_id: str, *, after: bool, outcome: str = "cited", rank: int = 1) -> tuple:
    return (
        item_id,
        "某个模型发布了",
        "Hugging Face",
        datetime(2026, 8, 18, tzinfo=timezone.utc),
        outcome,
        rank,
        rank,
        "正文摘录",
        after,
    )


def _candidate() -> dict:
    return {
        "query_id": "0e9f2f7a-0000-0000-0000-000000000000",
        "question": "智谱最近发布了什么？",
        "band": "weak_support",
        "asked_at": "2026-08-10T13:50:17+00:00",
        "worst_support": 0.0081,
    }


# --- what an annotator is allowed to grade --------------------------------


def test_a_document_published_after_the_question_gets_no_id_line() -> None:
    """Evaluation clamps retrieval to `asked_at`. Grading such an item books a
    recall miss that no retrieval change could ever fix — so the row is shown
    for context and the grade line is withheld."""
    sheet = render(
        _Connection([_row("in-window", after=False), _row("later", after=True, rank=2)]),
        [_candidate()],
        category="mixed",
    )
    assert "- {id: in-window, grade: ?}" in sheet
    assert "- {id: later" not in sheet
    # Shown, not hidden: the funnel is still what it is.
    assert "·快照外]" in sheet
    assert sheet.count("↑ 发布时间晚于提问时间") == 1


def test_a_question_whose_candidates_are_all_out_of_snapshot_says_so() -> None:
    """Otherwise it renders as answerable with an empty item list, which the
    golden loader rejects for a reason the sheet never explained."""
    sheet = render(_Connection([_row("later", after=True)]), [_candidate()], category="mixed")
    assert "候选全部落在快照外" in sheet
    # No gradable row at all — not even the one the funnel surfaced.
    assert "- {id:" not in sheet


def test_the_sheet_asks_for_a_category_per_question() -> None:
    """`data/golden/` is one file per category, so the split needs this and
    nothing else in the pipeline can infer it."""
    sheet = render(_Connection([_row("a", after=False)]), [_candidate()], category="mixed")
    assert "category: ?" in sheet
    for category in CATEGORIES:
        assert category in sheet


# --- what an unfinished sheet must not pass -------------------------------


def test_unfilled_grades_and_placeholder_ids_are_refused() -> None:
    sheet = render(_Connection([_row("a", after=False)]), [_candidate()], category="mixed")
    problems = validate(sheet)
    assert any("grade: ?" in p for p in problems)
    assert any("占位 id" in p for p in problems)
    assert any("notes" in p for p in problems)
    # Rendered as `category: ?`, so it reports as an unknown one rather than a
    # missing one — either way the sheet cannot be split until it is answered.
    assert any("category" in p for p in problems)


def test_a_rejected_candidate_may_keep_its_placeholder_id() -> None:
    """The `dropped:` block records candidates that were looked at and turned
    down. Those keep the mined id — it is the only handle on a question that
    never became one — and must not read as unfinished work."""
    filled = """
annotation:
  dropped:
    - id: TODO-9783d8fe
      reason: 与另一题重复
questions:
  - id: RAG-GOLD-091
    category: abstention
    answerable: false
    presupposition: "语料收录了智谱的发布"
    notes: "考信源覆盖缺口"
"""
    assert validate(filled) == []


def test_an_unanswerable_question_needs_a_presupposition() -> None:
    """It is what the abstention judge reads. Without it the question grades as
    answerable-with-no-evidence, a much weaker test."""
    problems = validate(
        '\nquestions:\n  - id: RAG-GOLD-091\n    category: abstention\n'
        '    answerable: false\n    notes: "x"\n'
    )
    assert any("presupposition" in p for p in problems)


def test_must_not_claim_is_not_demanded() -> None:
    """RAG-GOLD-077 and 080 are well-formed without one. Requiring it would push
    an annotator to invent a forbidden string, and a wrong one is worse than
    none: it fails answers that correctly name the thing while denying it."""
    problems = validate(
        '\nquestions:\n  - id: RAG-GOLD-091\n    category: abstention\n'
        '    answerable: false\n    presupposition: "x"\n    notes: "y"\n'
    )
    assert problems == []


def test_an_unknown_category_is_refused() -> None:
    problems = validate(
        '\nquestions:\n  - id: RAG-GOLD-091\n    category: 杂项\n'
        '    answerable: true\n    notes: "x"\n'
    )
    assert any("不在" in p for p in problems)

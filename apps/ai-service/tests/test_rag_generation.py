"""Generation-side quality metrics."""

from datetime import UTC, datetime
from typing import Any

from ahr.rag.answer import Answer, Citation
from ahr.rag.eval.generation import (
    GenerationResult,
    citation_coverage,
    score_answer,
    summarise,
)
from ahr.rag.eval.golden import GoldenQuestion


def test_citation_after_terminal_punctuation_belongs_to_the_sentence() -> None:
    assert citation_coverage("GLM-5.2 已上线。[1]") == 1.0
    assert citation_coverage("GLM-5.2 已上线[1]。") == 1.0


def test_a_following_uncited_sentence_still_reduces_coverage() -> None:
    assert citation_coverage("GLM-5.2 已上线。[1] 第二句没有引用。") == 0.5


def test_refusal_is_measured_by_over_refusal_not_citation_completeness() -> None:
    answered = GenerationResult(
        question_id="ok",
        category="fact_check",
        answerable=True,
        refused=False,
        citations=1,
        citation_coverage=1.0,
    )
    refused = GenerationResult(
        question_id="miss",
        category="fact_check",
        answerable=True,
        refused=True,
        citations=0,
        citation_coverage=0.0,
    )
    overall = summarise([answered, refused])["overall"]
    assert overall["citation_coverage"] == 1.0
    assert overall["over_refusal_rate"] == 0.5
    assert overall["answered"] == 1


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _Connection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def cursor(self) -> _Cursor:
        return _Cursor(self.rows)


def test_a_scored_answer_keeps_each_citation_it_was_scored_on() -> None:
    """Re-scoring a change to the anchors must not need the ninety answers again."""
    citation = Citation(
        number=1,
        chunk_id="chunk-a",
        content_item_id="item-a",
        claim_text="API 价格打 8 折。",
        title="t",
        source_name="s",
        canonical_url="https://example.com/a",
        published_at=None,
        support_score=0.91,
    )
    answer = Answer(question="q", answer_markdown="API 价格打 8 折。[1]", citations=[citation])
    question = GoldenQuestion(
        id="RAG-X",
        category="fact_check",
        question="q",
        asked_at=datetime(2026, 8, 3, tzinfo=UTC),
        answerable=True,
    )
    result = score_answer(_Connection([("chunk-a", "body", "item-a", None)]), question, answer)
    assert result.cited == [
        {
            "number": 1,
            "chunk_id": "chunk-a",
            "item_id": "item-a",
            "claim": "API 价格打 8 折。",
            "support": 0.91,
        }
    ]

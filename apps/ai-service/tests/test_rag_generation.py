"""Generation-side quality metrics."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from ahr.rag.answer import Answer, Citation
from ahr.rag.eval.generation import (
    GenerationResult,
    citation_coverage,
    score_answer,
    sentence_support,
    summarise,
)
from ahr.rag.eval.golden import GoldenQuestion
from ahr.rag.rerank import RerankUnavailableError


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


class _Reranker:
    """Scores (passage, parent) from a table keyed by the sentence."""

    def __init__(self, table: dict[str, tuple[float, float]] | None) -> None:
        self.table = table
        self.calls = 0

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int
    ) -> list[tuple[int, float]]:
        self.calls += 1
        if self.table is None:
            raise RerankUnavailableError("down")
        passage, parent = self.table[query]
        return [(0, passage), (1, parent)]


def _cite(number: int, chunk_id: str) -> Citation:
    return Citation(
        number=number,
        chunk_id=chunk_id,
        content_item_id=f"item-{chunk_id}",
        claim_text="x",
        title="t",
        source_name="s",
        canonical_url="https://example.com",
        published_at=None,
    )


def test_every_published_pair_is_scored_on_both_bases() -> None:
    """A marker shared by two sentences is two things a reader checks."""
    answer = Answer(
        question="q",
        answer_markdown="融资约 50 亿美元。[1] 六成投向研发。[1][2]",
        citations=[_cite(1, "a"), _cite(2, "b")],
    )
    reranker = _Reranker({"融资约 50 亿美元。": (0.1, 0.9), "六成投向研发。": (0.8, 0.9)})
    result = asyncio.run(
        sentence_support(reranker, answer, {"a": "A", "b": "B"}, {"a": "PA", "b": "PB"})  # type: ignore[arg-type]
    )
    assert result == (3, 2, 3)
    assert reranker.calls == 3


def test_an_outage_is_not_a_zero() -> None:
    answer = Answer(question="q", answer_markdown="一句。[1]", citations=[_cite(1, "a")])
    result = asyncio.run(
        sentence_support(_Reranker(None), answer, {"a": "A"}, {"a": "PA"})  # type: ignore[arg-type]
    )
    assert result is None


def test_sentence_support_is_pooled_over_pairs_not_averaged_per_answer() -> None:
    small = GenerationResult(
        question_id="a",
        category="fact_check",
        answerable=True,
        refused=False,
        sentence_pairs=1,
        sentence_supported=0,
        sentence_supported_as_read=1,
    )
    large = GenerationResult(
        question_id="b",
        category="fact_check",
        answerable=True,
        refused=False,
        sentence_pairs=9,
        sentence_supported=9,
        sentence_supported_as_read=9,
    )
    overall = summarise([small, large])["overall"]
    assert overall["sentence_pairs"] == 10
    assert overall["sentence_support_supported"] == 0.9  # a per-answer mean would say 0.5
    assert overall["sentence_support_as_read_supported"] == 1.0

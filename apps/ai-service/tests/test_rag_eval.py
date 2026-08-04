"""Tests for the RAG evaluation machinery.

Every metric is checked against a value computed by hand in the test itself.
A metric implementation that is merely self-consistent is worthless: it will
happily report a stable, wrong number for the entire life of the project.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from ahr.rag.eval.golden import (
    CATEGORIES,
    MIN_PER_CATEGORY,
    GoldenSetError,
    load_golden_set,
)
from ahr.rag.eval.metrics import (
    RankedResult,
    dedupe_to_items,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from ahr.rag.retrieval import ChunkHit, _escape_lexeme, interleave


def _find_golden_dir() -> Path | None:
    """Locate the golden set from either checkout layout.

    Running from a source checkout puts it four levels up from this file; the
    test image mounts it at /app/data. Guessing one and skipping on the other
    would make the shipped-set checks silently vanish in CI.
    """
    mounted = Path("/app/data/golden")
    if mounted.is_dir():
        return mounted

    # Walk up rather than index a fixed number of parents: the test image has
    # only /app above tests/, so parents[3] raises IndexError there.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "golden"
        if candidate.is_dir():
            return candidate
    return None


GOLDEN_DIR = _find_golden_dir()


def _ranked(*item_ids: str) -> list[RankedResult]:
    return [
        RankedResult(item_id=item_id, score=1.0 - index * 0.01)
        for index, item_id in enumerate(item_ids)
    ]


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------


def test_recall_counts_distinct_relevant_items_found() -> None:
    ranked = _ranked("a", "x", "b", "y")
    assert recall_at_k(ranked, frozenset({"a", "b", "c"}), 4) == pytest.approx(2 / 3)


def test_recall_respects_the_cutoff() -> None:
    ranked = _ranked("x", "y", "a")
    # "a" sits at rank 3, so it is outside the top 2.
    assert recall_at_k(ranked, frozenset({"a"}), 2) == 0.0
    assert recall_at_k(ranked, frozenset({"a"}), 3) == 1.0


def test_recall_without_relevant_items_is_an_error_not_a_zero() -> None:
    # Scoring an unanswerable question as 0.0 recall would drag the mean down
    # for a question that has nothing to recall; scoring it 1.0 would inflate
    # it. Neither is meaningful, so the caller must exclude it explicitly.
    with pytest.raises(ValueError):
        recall_at_k(_ranked("x"), frozenset(), 10)


def test_reciprocal_rank_uses_the_first_hit() -> None:
    ranked = _ranked("x", "y", "a", "b")
    assert reciprocal_rank(ranked, frozenset({"a", "b"})) == pytest.approx(1 / 3)


def test_reciprocal_rank_is_zero_when_nothing_was_retrieved() -> None:
    assert reciprocal_rank(_ranked("x", "y"), frozenset({"a"})) == 0.0


def test_ndcg_is_one_for_the_ideal_ordering() -> None:
    grades = {"a": 2, "b": 1}
    assert ndcg_at_k(_ranked("a", "b", "x"), grades, 10) == pytest.approx(1.0)


def test_ndcg_penalises_putting_the_supporting_item_first() -> None:
    grades = {"a": 2, "b": 1}
    # DCG = 1/log2(2) + 3/log2(3) = 1 + 1.8927 = 2.8927
    # IDCG = 3/log2(2) + 1/log2(3) = 3 + 0.6309 = 3.6309
    expected = (1 / math.log2(2) + 3 / math.log2(3)) / (3 / math.log2(2) + 1 / math.log2(3))
    assert ndcg_at_k(_ranked("b", "a"), grades, 10) == pytest.approx(expected)
    assert expected < 1.0


def test_ndcg_grade_two_is_worth_three_times_grade_one() -> None:
    # 2**2 - 1 = 3 against 2**1 - 1 = 1. The gap is the reason for grading at
    # all: a retriever that fills the top with merely-related documents must
    # not score like one that puts the answer first.
    top_answer = ndcg_at_k(_ranked("a", "z"), {"a": 2, "b": 1}, 10)
    top_support = ndcg_at_k(_ranked("b", "z"), {"a": 2, "b": 1}, 10)
    assert top_answer > top_support


def test_ndcg_respects_the_cutoff() -> None:
    grades = {"a": 2}
    assert ndcg_at_k(_ranked("x", "y", "a"), grades, 2) == 0.0
    assert ndcg_at_k(_ranked("x", "y", "a"), grades, 3) > 0.0


# --------------------------------------------------------------------------
# chunk -> item collapsing
# --------------------------------------------------------------------------


def test_dedupe_keeps_the_best_rank_per_item() -> None:
    hits = [("doc1", 0.9), ("doc1", 0.8), ("doc2", 0.7), ("doc1", 0.6)]
    ranked = dedupe_to_items(hits)
    assert [r.item_id for r in ranked] == ["doc1", "doc2"]
    assert ranked[0].score == pytest.approx(0.9)


def test_dedupe_prevents_one_document_from_inflating_recall() -> None:
    """A document occupying five of the top six chunk slots must occupy one
    item slot. Without this, "top 10" silently means "top 2 documents" and
    every recall number is wrong in the flattering direction."""
    hits = [("doc1", 0.9)] * 5 + [("doc2", 0.5), ("target", 0.4)]
    ranked = dedupe_to_items(hits)
    assert len(ranked) == 3
    # The target is at item-rank 3, not chunk-rank 7.
    assert recall_at_k(ranked, frozenset({"target"}), 3) == 1.0


def test_dedupe_of_an_empty_result_is_empty() -> None:
    assert dedupe_to_items([]) == []


# --------------------------------------------------------------------------
# sparse channel merging
# --------------------------------------------------------------------------


def _hit(chunk_id: str, item_id: str, score: float = 0.5) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        content_item_id=item_id,
        score=score,
        title="",
        source_name="",
    )


def test_interleave_alternates_between_channels() -> None:
    dense = [_hit("d1", "i1"), _hit("d2", "i2")]
    sparse = [_hit("s1", "i3"), _hit("s2", "i4")]
    assert [h.chunk_id for h in interleave(dense, sparse)] == ["d1", "s1", "d2", "s2"]


def test_interleave_keeps_the_earlier_position_of_a_shared_chunk() -> None:
    shared = _hit("c1", "i1")
    dense = [shared, _hit("d2", "i2")]
    sparse = [_hit("s1", "i3"), shared]
    merged = interleave(dense, sparse)
    assert [h.chunk_id for h in merged] == ["c1", "s1", "d2"]
    assert len(merged) == len({h.chunk_id for h in merged})


def test_interleave_drains_the_longer_channel() -> None:
    dense = [_hit("d1", "i1"), _hit("d2", "i2"), _hit("d3", "i3")]
    sparse = [_hit("s1", "i4")]
    assert [h.chunk_id for h in interleave(dense, sparse)] == ["d1", "s1", "d2", "d3"]


def test_interleave_of_empty_channels_is_empty() -> None:
    # A question with no distinctive term yields no sparse hits at all; the
    # merge must degrade to the dense ranking rather than fail.
    dense = [_hit("d1", "i1")]
    assert [h.chunk_id for h in interleave(dense, [])] == ["d1"]
    assert interleave([], []) == []


def test_lexeme_quoting_survives_an_apostrophe() -> None:
    # Lexemes come straight out of the corpus, so a tsquery built by string
    # concatenation has to escape them; "simon willison's" would otherwise
    # terminate the quoted term and produce a syntax error at query time.
    assert _escape_lexeme("o'reilly") == "'o''reilly'"
    assert _escape_lexeme("llama.cpp") == "'llama.cpp'"


# --------------------------------------------------------------------------
# golden set loading and validation
# --------------------------------------------------------------------------


def _write(directory: Path, name: str, payload: dict[str, object]) -> None:
    (directory / name).write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def test_rejects_naive_asked_at(tmp_path: Path) -> None:
    # A timestamp without an offset resolves differently depending on where the
    # evaluation runs. That is the same class of defect that made the whole
    # site render UTC eight hours behind Beijing.
    _write(
        tmp_path,
        "x.yaml",
        {
            "category": "fact_check",
            "questions": [
                {
                    "id": "Q1",
                    "question": "q",
                    "asked_at": "2026-08-03T12:00:00",
                    "answerable": True,
                    "relevant_items": [{"id": "i1", "grade": 2}],
                }
            ],
        },
    )
    with pytest.raises(GoldenSetError, match="timezone"):
        load_golden_set(tmp_path, require_full=False)


def test_rejects_unanswerable_question_carrying_relevant_items(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "x.yaml",
        {
            "category": "abstention",
            "questions": [
                {
                    "id": "Q1",
                    "question": "q",
                    "asked_at": "2026-08-03T12:00:00+08:00",
                    "answerable": False,
                    "relevant_items": [{"id": "i1", "grade": 2}],
                }
            ],
        },
    )
    with pytest.raises(GoldenSetError, match="must not list relevant items"):
        load_golden_set(tmp_path, require_full=False)


def test_rejects_answerable_question_without_relevant_items(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "x.yaml",
        {
            "category": "fact_check",
            "questions": [
                {
                    "id": "Q1",
                    "question": "q",
                    "asked_at": "2026-08-03T12:00:00+08:00",
                    "answerable": True,
                }
            ],
        },
    )
    with pytest.raises(GoldenSetError, match="at least one relevant item"):
        load_golden_set(tmp_path, require_full=False)


def test_rejects_duplicate_question_ids_across_files(tmp_path: Path) -> None:
    question = {
        "id": "Q1",
        "question": "q",
        "asked_at": "2026-08-03T12:00:00+08:00",
        "answerable": True,
        "relevant_items": [{"id": "i1", "grade": 2}],
    }
    _write(tmp_path, "a.yaml", {"category": "fact_check", "questions": [question]})
    _write(tmp_path, "b.yaml", {"category": "explainer", "questions": [question]})
    with pytest.raises(GoldenSetError, match="duplicate question ids"):
        load_golden_set(tmp_path, require_full=False)


def test_rejects_out_of_range_grade(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "x.yaml",
        {
            "category": "fact_check",
            "questions": [
                {
                    "id": "Q1",
                    "question": "q",
                    "asked_at": "2026-08-03T12:00:00+08:00",
                    "answerable": True,
                    "relevant_items": [{"id": "i1", "grade": 3}],
                }
            ],
        },
    )
    with pytest.raises(GoldenSetError, match="grade must be"):
        load_golden_set(tmp_path, require_full=False)


def test_require_full_enforces_the_per_category_minimum(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "x.yaml",
        {
            "category": "fact_check",
            "questions": [
                {
                    "id": "Q1",
                    "question": "q",
                    "asked_at": "2026-08-03T12:00:00+08:00",
                    "answerable": True,
                    "relevant_items": [{"id": "i1", "grade": 2}],
                }
            ],
        },
    )
    with pytest.raises(GoldenSetError, match="requires at least"):
        load_golden_set(tmp_path, require_full=True)


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(GoldenSetError, match="no golden set files"):
        load_golden_set(tmp_path, require_full=False)


# --------------------------------------------------------------------------
# the real golden set
# --------------------------------------------------------------------------


@pytest.mark.skipif(GOLDEN_DIR is None, reason="golden set not mounted")
def test_shipped_golden_set_is_valid_and_complete() -> None:
    assert GOLDEN_DIR is not None
    golden = load_golden_set(GOLDEN_DIR, require_full=True)
    assert len(golden) == 90
    for category in CATEGORIES:
        assert len(golden.by_category(category)) >= MIN_PER_CATEGORY


@pytest.mark.skipif(GOLDEN_DIR is None, reason="golden set not mounted")
def test_shipped_golden_set_has_enough_unanswerable_questions() -> None:
    """Abstention is a locked constraint, not a nice-to-have. A set without
    real unanswerable questions cannot detect a system that never refuses."""
    assert GOLDEN_DIR is not None
    golden = load_golden_set(GOLDEN_DIR, require_full=True)
    unanswerable = [q for q in golden.questions if not q.answerable]
    assert len(unanswerable) >= 10


@pytest.mark.skipif(GOLDEN_DIR is None, reason="golden set not mounted")
def test_shipped_golden_set_ids_are_sequential_and_unique() -> None:
    assert GOLDEN_DIR is not None
    golden = load_golden_set(GOLDEN_DIR, require_full=True)
    numbers = sorted(int(q.id.rsplit("-", 1)[1]) for q in golden.questions)
    assert numbers == list(range(1, 91))

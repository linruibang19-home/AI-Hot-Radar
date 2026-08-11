"""Retrieval metrics.

Recall and MRR are kept separate on purpose, because they answer different
questions and point at different fixes:

    Recall@20 low   → the candidate set is missing the answer.
                      Tuning the reranker cannot help; the recall channel is
                      the thing to change.
    Recall@20 high
    but MRR low     → the answer is present but buried. Fusion weights and
                      reranking are where the gain is.

Collapsing them into one "quality" number destroys exactly the signal that
decides where the next hour of work goes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ahr.rag.retrieval import ChunkHit


@dataclass(frozen=True)
class RankedResult:
    """One retrieved content_item, at the rank the retriever placed it."""

    item_id: str
    score: float
    source_id: str = ""
    source_tier: str = ""


def recall_at_k(ranked: list[RankedResult], relevant: frozenset[str], k: int) -> float:
    """Fraction of the relevant items that appear in the top k.

    Undefined when nothing is relevant; callers must exclude unanswerable
    questions rather than let them count as a perfect or zero score.
    """
    if not relevant:
        raise ValueError("recall is undefined without relevant items")
    hits = sum(1 for result in ranked[:k] if result.item_id in relevant)
    return hits / len(relevant)


def reciprocal_rank(ranked: list[RankedResult], relevant: frozenset[str]) -> float:
    """1 / rank of the first relevant item, or 0 if none was retrieved."""
    if not relevant:
        raise ValueError("reciprocal rank is undefined without relevant items")
    for position, result in enumerate(ranked, start=1):
        if result.item_id in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked: list[RankedResult], grades: dict[str, int], k: int) -> float:
    """Graded gain, normalised by the best achievable ordering.

    Gain is `2**grade - 1`, so a grade-2 item (directly answers the question) is
    worth three times a grade-1 item (supporting context) rather than twice.
    That gap is the point of grading at all: a retriever that fills the top with
    merely-related documents should not score like one that puts the answer
    first.
    """
    if not grades:
        raise ValueError("nDCG is undefined without relevant items")

    def dcg(gains: list[int]) -> float:
        return sum(gain / math.log2(position + 1) for position, gain in enumerate(gains, start=1))

    actual = [(2 ** grades.get(result.item_id, 0)) - 1 for result in ranked[:k]]
    ideal = sorted(((2**grade) - 1 for grade in grades.values()), reverse=True)[:k]

    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0:
        return 0.0
    return dcg(actual) / ideal_dcg


def dedupe_to_items(chunk_hits: list[tuple[str, float]]) -> list[RankedResult]:
    """Collapse a chunk ranking into an item ranking, keeping the best rank.

    Retrieval returns passages; the golden set is annotated on documents. A
    document that occupies five of the top ten chunk slots must occupy exactly
    one item slot, otherwise "top 10" silently means "top 3 documents" and every
    recall number is inflated.

    Input is `(content_item_id, score)` in retrieval order.
    """
    seen: set[str] = set()
    ranked: list[RankedResult] = []
    for item_id, score in chunk_hits:
        if item_id in seen:
            continue
        seen.add(item_id)
        ranked.append(RankedResult(item_id=item_id, score=score))
    return ranked


def dedupe_hits_to_items(chunk_hits: list[ChunkHit]) -> list[RankedResult]:
    """Collapse ``ChunkHit`` objects while retaining source diagnostics.

    The original tuple helper remains the small metric primitive used by unit
    tests and sweep code.  Evaluation reports need the source identity and tier
    as well, otherwise `source diversity` and `primary-source@5` from §14 are
    impossible to measure even though retrieval already returns that metadata.
    """
    seen: set[str] = set()
    ranked: list[RankedResult] = []
    for hit in chunk_hits:
        item_id = hit.content_item_id
        if item_id in seen:
            continue
        seen.add(item_id)
        ranked.append(
            RankedResult(
                item_id=item_id,
                score=hit.score,
                source_id=hit.source_id,
                source_tier=hit.source_tier,
            )
        )
    return ranked


def source_diagnostics(ranked: list[RankedResult], *, depth: int = 10) -> dict[str, float | int]:
    """Source concentration and primary evidence ratio at an item cutoff."""
    rows = ranked[:depth]
    if not rows:
        return {
            "distinct_sources": 0,
            "dominant_source_share": 0.0,
            "primary_source_share": 0.0,
        }

    counts: dict[str, int] = {}
    for index, row in enumerate(rows):
        # Missing provenance must not collapse unrelated items into one fake
        # source.  Keep it visible as an item-specific unknown instead.
        key = row.source_id or f"unknown:{index}"
        counts[key] = counts.get(key, 0) + 1
    primary_depth = min(5, len(ranked))
    primary = sum(1 for row in ranked[:primary_depth] if row.source_tier == "primary")
    return {
        "distinct_sources": len(counts),
        "dominant_source_share": max(counts.values()) / len(rows),
        "primary_source_share": primary / primary_depth if primary_depth else 0.0,
    }

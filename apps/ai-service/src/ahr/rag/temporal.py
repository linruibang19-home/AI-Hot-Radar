"""Recency as a ranking signal after reranking (AHR-RAG-400 §6 `temporal_fit`).

B4 improved every category except one. `recent_updates` MRR fell from 0.7333 to
0.6484, and the cause is not subtle: a cross-encoder scores how well a passage
answers the question, and nothing in "Cloudflare 最近有什么新动作" tells it that
a release from this morning beats an equally-relevant one from three weeks ago.
For this product recency *is* part of relevance, and the reranker cannot see it.

§6 lists four dimensions a reranker should produce — `relevance`, `directness`,
`temporal_fit`, `source_fit` — and the hosted cross-encoder returns only the
first. This module supplies `temporal_fit` as a bounded blend applied after
reranking, for the query types that asked for freshness.

Bounded, and only then. Two lessons are baked into that:

* the first B3 run applied §6's boosts to raw RRF scores whose entire spread was
  smaller than the boosts, and metadata silently became the ranking function;
* a question like "NEO-Unify 架构是怎么工作的" has no time sense at all, and
  sorting its evidence by publication date would be actively wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# How much of the final score recency may account for, for freshness-seeking
# queries. Deliberately a minority share: the answer still has to be relevant,
# and a merely-recent passage must not outrank one that actually answers.
TEMPORAL_WEIGHT = 0.30


@dataclass(frozen=True)
class Scored:
    key: str
    relevance: float
    published_at: datetime | None


def _normalise(values: list[float]) -> list[float]:
    """Map onto [0, 1]. A flat list becomes all-1.0 rather than all-0.

    Collapsing ties to zero would let the recency term decide everything on the
    (common) case where the reranker scores several passages identically.
    """
    if not values:
        return []
    low, high = min(values), max(values)
    spread = high - low
    if spread <= 0:
        return [1.0] * len(values)
    return [(value - low) / spread for value in values]


def recency_scores(
    items: list[Scored],
    window: tuple[datetime, datetime] | None,
) -> list[float]:
    """Position within the searched window, oldest 0.0 and newest 1.0.

    Scaled against the window rather than against an absolute half-life: the
    reader asked about a period, so "recent" means recent *for that period*.
    Seven days and thirty days should both spread their contents across the
    full range instead of one of them collapsing to a single value.

    An item without a publication date scores 0.5 — neither promoted nor
    punished for something the source failed to state.
    """
    if not items:
        return []
    if window is None:
        return [0.5] * len(items)

    start, end = window
    span = (end - start).total_seconds()
    if span <= 0:
        return [0.5] * len(items)

    scores: list[float] = []
    for item in items:
        if item.published_at is None:
            scores.append(0.5)
            continue
        position = (item.published_at - start).total_seconds() / span
        scores.append(min(1.0, max(0.0, position)))
    return scores


def apply_temporal_fit(
    items: list[Scored],
    *,
    window: tuple[datetime, datetime] | None,
    freshness_required: bool,
    weight: float = TEMPORAL_WEIGHT,
) -> list[str]:
    """Reorder by relevance blended with recency; return keys, best first.

    When the question carries no time sense the input order is returned
    untouched. That is not an optimisation — reordering an explainer's evidence
    by date would put the newest mention of an architecture above the article
    that explains it.
    """
    if not items:
        return []
    if not freshness_required:
        return [item.key for item in items]

    relevance = _normalise([item.relevance for item in items])
    recency = recency_scores(items, window)

    blended = [
        ((1 - weight) * rel + weight * rec, item.key)
        for rel, rec, item in zip(relevance, recency, items, strict=True)
    ]
    # Ties broken by key so two runs of the evaluation cannot differ for
    # reasons that have nothing to do with the retrieval.
    blended.sort(key=lambda pair: (-pair[0], pair[1]))
    return [key for _, key in blended]

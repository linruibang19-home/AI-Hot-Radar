"""Adaptive retrieval depth, decided by measurement (T3-7, B12).

The idea behind adaptive RAG is that easy questions should not pay for the
expensive path. The obvious version of that — "simple factual questions can skip
the reranker" — is **wrong here, and the golden set says so loudly**:

    B3 → B4, MRR by category (reranker off → on)

        fact_check      0.7472 → 0.9667   +0.2195
        timeline        0.6249 → 0.9022   +0.2773
        explainer       0.6952 → 0.9667   +0.2715
        comparison      0.6430 → 0.8244   +0.1814
        recent_updates  0.7333 → 0.6484   −0.0849   (fixed later by B7)
        abstention      0.7500 → 0.7500   ±0

`fact_check` — the category a router would most naturally send down the cheap
path — gains the second most from reranking. The intuition is exactly inverted.
The only category the reranker leaves untouched is `abstention`, and B1 already
established that unanswerable questions cannot be identified up front: their
similarity scores overlap answerable ones by 0.14, so there is no threshold to
route on.

A second candidate rule died on contact with the data too. "Skip the reranker
when few candidates survived fusion" is sound in principle — if the candidate
set is no larger than the evidence budget, reordering cannot change *which*
passages the model reads. In 128 real queries the fused count never fell below
60. The rule is correct and never fires.

**What the data does support is depth, not presence.** B12 ran the full pipeline
at 20 candidates against the incumbent 40:

    overall            MRR 0.8438 vs 0.8731   (−0.0293, so not a global change)

    comparison         0.8244 vs 0.8244   ±0.0000   ← identical, rank for rank
    recent_updates     0.7522 vs 0.7522   ±0.0000   ← identical, rank for rank
    timeline           0.9111 vs 0.9467   −0.0356
    fact_check         0.8407 vs 0.9000   −0.0593
    explainer          0.9035 vs 0.9667   −0.0632

Two categories are unchanged by the extra twenty candidates and three are not.
So the router halves the cross-encoder's work for those two and leaves the rest
alone — the same shape as B7's temporal blend, which applies only where it was
measured to help and is rank-for-rank inert everywhere else.

**Sample size, stated rather than buried:** 15 questions per category. "±0.0000"
means the two runs produced identical orderings on those 15, which is a strong
signal for a deterministic reranker but is not a claim about all questions of
that type. Re-run B12 before widening the fast set.
"""

from __future__ import annotations

from dataclasses import dataclass

# B4 measured 40 as better than 100 on every metric and 3.2x faster.
DEFAULT_CANDIDATES = 40

# B12: no measured difference for the categories below.
FAST_CANDIDATES = 20

# Only these two. Adding a category here without re-running B12 is how a
# latency saving quietly becomes a quality regression.
FAST_QUERY_TYPES = frozenset({"comparison", "recent_updates"})


@dataclass(frozen=True)
class Route:
    """How much work this question gets, and why."""

    rerank_candidates: int
    fast: bool
    reason: str

    def as_metrics(self) -> dict[str, object]:
        return {
            "path": "fast" if self.fast else "full",
            "rerank_candidates": self.rerank_candidates,
            "reason": self.reason,
        }


def choose(query_type: str) -> Route:
    """Pick the retrieval depth for one question type."""
    if query_type in FAST_QUERY_TYPES:
        return Route(
            rerank_candidates=FAST_CANDIDATES,
            fast=True,
            reason=f"B12: {query_type} scores identically at 20 and 40 candidates",
        )
    return Route(
        rerank_candidates=DEFAULT_CANDIDATES,
        fast=False,
        reason=f"B12: {query_type} loses MRR below 40 candidates",
    )

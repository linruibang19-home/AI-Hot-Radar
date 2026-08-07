"""Adaptive retrieval depth (T3-7, B12).

Most of what is worth pinning here is *restraint*. Two intuitive routing rules
were tried and rejected by the golden set, and the failure mode of re-adding one
is silent: latency improves, the page still renders, and MRR drops by six points
in a category nobody re-measured.
"""

from __future__ import annotations

import inspect

from ahr.rag import router, service


def test_the_two_measured_categories_take_the_shallow_path() -> None:
    """B12: identical MRR at 20 and 40 candidates, rank for rank."""
    for query_type in ("comparison", "recent_updates"):
        route = router.choose(query_type)
        assert route.fast
        assert route.rerank_candidates == router.FAST_CANDIDATES


def test_every_other_category_keeps_the_full_depth() -> None:
    """B12: explainer −6.3pt, fact_check −5.9pt, timeline −3.6pt at depth 20."""
    for query_type in ("explainer", "fact_check", "timeline", "recommendation"):
        route = router.choose(query_type)
        assert not route.fast
        assert route.rerank_candidates == router.DEFAULT_CANDIDATES


def test_an_unknown_query_type_gets_the_full_path() -> None:
    """Unrouted is not the same as cheap. A new question type has no measurement
    behind it, so it takes the configuration that was measured."""
    assert router.choose("something_new").rerank_candidates == router.DEFAULT_CANDIDATES


def test_the_fast_set_stays_small() -> None:
    """A guard against the tempting edit. `fact_check` is the category a router
    would most naturally send down the cheap path, and B3→B4 measured it gaining
    +0.2195 MRR from reranking — the intuition is exactly inverted here."""
    assert set(router.FAST_QUERY_TYPES) == {"comparison", "recent_updates"}
    assert "fact_check" not in router.FAST_QUERY_TYPES
    assert "explainer" not in router.FAST_QUERY_TYPES


def test_the_shallow_path_is_actually_shallower() -> None:
    assert router.FAST_CANDIDATES < router.DEFAULT_CANDIDATES


def test_the_route_is_recorded_with_its_reason() -> None:
    """A routing decision nobody can see is a routing decision nobody can
    audit — and this one trades quality for latency."""
    metrics = router.choose("comparison").as_metrics()

    assert metrics["path"] == "fast"
    assert metrics["rerank_candidates"] == router.FAST_CANDIDATES
    assert "B12" in str(metrics["reason"])


def test_retrieval_uses_the_route_rather_than_a_constant() -> None:
    source = inspect.getsource(service.retrieve)
    assert "route = choose_route(retrieval_plan.query_type)" in source
    assert "hits[: route.rerank_candidates]" in source
    # And the decision reaches the metrics blob, which is what `/ops` reads.
    assert '"route": route.as_metrics()' in source

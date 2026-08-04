"""Recency blending after reranking (B7, AHR-RAG-400 §6 `temporal_fit`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ahr.rag.temporal import Scored, apply_temporal_fit, recency_scores

WINDOW = (datetime(2026, 7, 28, tzinfo=UTC), datetime(2026, 8, 4, tzinfo=UTC))


def _item(key: str, relevance: float, days_after_start: float | None) -> Scored:
    published = (
        WINDOW[0] + timedelta(days=days_after_start) if days_after_start is not None else None
    )
    return Scored(key=key, relevance=relevance, published_at=published)


# --------------------------------------------------------------------------
# recency scoring
# --------------------------------------------------------------------------


def test_recency_spans_the_window_not_an_absolute_scale() -> None:
    """The reader asked about a period, so "recent" means recent for that
    period — a 7-day and a 30-day window should each use the full range."""
    scores = recency_scores([_item("a", 1.0, 0), _item("b", 1.0, 7)], WINDOW)
    assert scores == [0.0, 1.0]


def test_a_missing_publication_date_sits_in_the_middle() -> None:
    # Neither promoted nor punished for something the source failed to state.
    assert recency_scores([_item("a", 1.0, None)], WINDOW) == [0.5]


def test_no_window_means_no_recency_signal() -> None:
    assert recency_scores([_item("a", 1.0, 0), _item("b", 1.0, 7)], None) == [0.5, 0.5]


def test_dates_outside_the_window_are_clamped() -> None:
    scores = recency_scores([_item("a", 1.0, -5), _item("b", 1.0, 99)], WINDOW)
    assert scores == [0.0, 1.0]


# --------------------------------------------------------------------------
# blending
# --------------------------------------------------------------------------


def test_recency_breaks_a_tie_between_equally_relevant_passages() -> None:
    """The exact case B4 lost: a cross-encoder cannot tell that this morning's
    release beats an equally-relevant one from three weeks ago."""
    order = apply_temporal_fit(
        [_item("old", 0.9, 0), _item("new", 0.9, 7)],
        window=WINDOW,
        freshness_required=True,
    )
    assert order == ["new", "old"]


def test_relevance_still_dominates() -> None:
    # Recency is a minority share on purpose. A merely-recent passage must not
    # outrank one that actually answers the question — that would repeat the
    # first B3 run, where a bounded signal quietly became the ranking function.
    order = apply_temporal_fit(
        [_item("relevant", 1.0, 0), _item("recent", 0.0, 7)],
        window=WINDOW,
        freshness_required=True,
    )
    assert order == ["relevant", "recent"]


def test_a_timeless_question_is_left_completely_alone() -> None:
    """Sorting an explainer's evidence by date would put the newest mention of
    an architecture above the article that explains it."""
    items = [_item("b", 0.5, 0), _item("a", 0.4, 7)]
    assert apply_temporal_fit(items, window=WINDOW, freshness_required=False) == ["b", "a"]


def test_equal_relevance_scores_do_not_collapse_to_zero() -> None:
    # Normalising a flat list to zeros would hand the entire decision to
    # recency, which is common: the reranker ties often.
    order = apply_temporal_fit(
        [_item("x", 0.7, 3), _item("y", 0.7, 3)],
        window=WINDOW,
        freshness_required=True,
    )
    assert sorted(order) == ["x", "y"]


def test_ordering_is_deterministic_for_ties() -> None:
    items = [_item("b", 0.5, 3), _item("a", 0.5, 3)]
    first = apply_temporal_fit(items, window=WINDOW, freshness_required=True)
    second = apply_temporal_fit(items, window=WINDOW, freshness_required=True)
    assert first == second == ["a", "b"]


def test_an_empty_input_is_empty() -> None:
    assert apply_temporal_fit([], window=WINDOW, freshness_required=True) == []

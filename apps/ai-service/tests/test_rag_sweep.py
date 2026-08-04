"""Fusion weight grid search.

The sweep exists because `AHR-RAG-400` §5 forbids shipping the weights as
constants. What makes it cheap is that the channel outputs are captured once
and reused, so the properties worth pinning are the ones that make that reuse
valid — and the choice of decision metric, which is the whole argument.
"""

from __future__ import annotations

from ahr.rag.eval.sweep import (
    DECISION_DEPTH,
    SPARSE_GRID,
    TEMPORAL_GRID,
    Capture,
    score_weights,
    sweep,
)
from ahr.rag.retrieval import ChunkHit


def _hit(chunk: str, item: str, score: float = 0.5) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk,
        content_item_id=item,
        score=score,
        title=f"title-{item}",
        source_name="src",
    )


def _capture(
    *,
    dense: list[str],
    sparse: list[str],
    relevant: set[str],
    category: str = "fact_check",
) -> Capture:
    return Capture(
        question_id="q1",
        category=category,
        answerable=True,
        relevant_ids=relevant,
        channels={
            "dense": [_hit(f"d{i}", item) for i, item in enumerate(dense)],
            "sparse": [_hit(f"s{i}", item) for i, item in enumerate(sparse)],
        },
        metadata={},
    )


# --- the decision metric ---------------------------------------------------


def test_decision_depth_matches_the_rerank_candidate_set() -> None:
    """Fusion's job is to fill the reranker's candidate set; the reranker only
    reorders and can never introduce a document fusion missed. B4 fixed that
    set at 40, so a relevant item ranked 41st is invisible to everything
    downstream regardless of how good the ordering above it is."""
    assert DECISION_DEPTH == 40


def test_scoring_reports_the_decision_depth_and_the_continuity_depths() -> None:
    capture = _capture(dense=["a", "b"], sparse=["b", "c"], relevant={"a"})
    summary = score_weights([capture], {"dense": 1.0, "sparse": 0.6, "temporal": 0.15})

    assert f"recall@{DECISION_DEPTH}" in summary
    # B1-B7 are all reported at 10 and 20; dropping them would make this run
    # incomparable with every baseline before it.
    assert "recall@10" in summary
    assert "recall@20" in summary
    assert "mrr" in summary


# --- reuse of the captured channels ----------------------------------------


def test_captures_survive_being_scored_twice() -> None:
    """`apply_boosts` rewrites scores in place. If the sweep handed it the
    captured lists directly, configuration N+1 would fuse over scores already
    normalised by configuration N, and every result after the first would be
    measuring something that never ran."""
    capture = _capture(dense=["a", "b", "c"], sparse=["c", "b"], relevant={"a"})
    weights = {"dense": 1.0, "sparse": 0.6, "temporal": 0.15}

    first = score_weights([capture], weights)
    second = score_weights([capture], weights)

    assert first == second


def test_original_channel_scores_are_not_mutated() -> None:
    capture = _capture(dense=["a", "b"], sparse=["b"], relevant={"a"})
    before = [hit.score for hit in capture.channels["dense"]]

    score_weights([capture], {"dense": 1.0, "sparse": 0.6, "temporal": 0.15})

    assert [hit.score for hit in capture.channels["dense"]] == before


# --- what the weights actually do ------------------------------------------


def test_raising_the_sparse_weight_promotes_a_sparse_only_answer() -> None:
    """The direction the grid is searching in. RAG-GOLD-002 is the real case:
    rank 1 on sparse, rank 17 on dense."""
    capture = _capture(
        dense=["x", "y", "z", "answer"],
        sparse=["answer", "x"],
        relevant={"answer"},
    )

    low = score_weights([capture], {"dense": 1.0, "sparse": 0.1, "temporal": 0.0})
    high = score_weights([capture], {"dense": 1.0, "sparse": 2.0, "temporal": 0.0})

    assert high["mrr"] > low["mrr"]


def test_unanswerable_questions_are_excluded_from_the_score() -> None:
    """Recall and MRR are undefined with no relevant item; averaging a zero in
    would make a configuration look worse for answering an unanswerable
    question correctly."""
    answerable = _capture(dense=["a"], sparse=[], relevant={"a"})
    unanswerable = Capture(
        question_id="q2",
        category="abstention",
        answerable=False,
        relevant_ids=set(),
        channels={"dense": [_hit("d0", "junk")]},
        metadata={},
    )

    summary = score_weights([answerable, unanswerable], {"dense": 1.0, "sparse": 0.6})
    assert summary["scored"] == 1


# --- the grid --------------------------------------------------------------


def test_dense_stays_pinned_at_one_across_the_grid() -> None:
    """RRF is linear in the weights, so scaling all three scales every score
    equally and leaves the order identical. Sweeping dense as well would spend
    most of the grid re-measuring arithmetically identical configurations."""
    capture = _capture(dense=["a"], sparse=["a"], relevant={"a"})
    payload = sweep([capture])

    assert all(r["weights"]["dense"] == 1.0 for r in payload["results"])


def test_grid_covers_every_combination() -> None:
    capture = _capture(dense=["a"], sparse=["b"], relevant={"a"})
    payload = sweep([capture])

    assert payload["config"]["combinations"] == len(SPARSE_GRID) * len(TEMPORAL_GRID)


def test_results_are_ranked_by_the_decision_metric() -> None:
    capture = _capture(dense=["a", "b"], sparse=["b", "a"], relevant={"a"})
    payload = sweep([capture])

    scores = [r[f"recall@{DECISION_DEPTH}"] for r in payload["results"]]
    assert scores == sorted(scores, reverse=True)
    assert payload["best"] == payload["results"][0]


def test_grid_includes_the_incumbent_so_the_comparison_is_direct() -> None:
    """A sweep that cannot reproduce the shipped configuration cannot say
    whether it beat it."""
    assert 0.6 in SPARSE_GRID
    assert 0.15 in TEMPORAL_GRID


def test_grid_includes_dropping_each_channel() -> None:
    """Zero is a real candidate, not a degenerate one: B2 measured sparse-only
    Recall@20 at 0.4662 against dense's 0.8876, and the first B3 run showed a
    badly weighted temporal channel actively destroying recall."""
    assert 0.0 in SPARSE_GRID
    assert 0.0 in TEMPORAL_GRID


def test_empty_capture_list_does_not_crash_the_sweep() -> None:
    payload = sweep([])
    assert payload["best"] is None

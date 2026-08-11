"""Aggregating what retrieval did on real questions.

The golden set is 90 questions chosen in advance to cover six categories. This
aggregate is every question anyone actually asked — a different population, and
the only one that says whether the design holds outside the cases it was
designed against.

The first real reading was not flattering, which is the point: across 141 cited
passages the keyword channel was never the *only* channel to find one. The
argument for hybrid retrieval rested on a single anecdote, and this turns the
anecdote into a rate.
"""

from __future__ import annotations

import inspect

from ahr.rag import ops


def test_channel_attribution_counts_only_cited_evidence() -> None:
    """A passage nobody cited says nothing about whether the channel that found
    it mattered. Counting all candidates would make the sparse channel look
    productive purely for returning rows."""
    source = inspect.getsource(ops.retrieval_summary)
    attribution = source[source.index("'both'") :]
    assert "t.outcome = 'cited'" in attribution


def test_sparse_only_means_dense_never_returned_it() -> None:
    source = inspect.getsource(ops.retrieval_summary)
    assert "WHEN t.sparse_rank IS NOT NULL THEN 'sparse_only'" in source
    # `both` has to be tested first, or every passage found by two channels
    # would be attributed to whichever branch happened to come first.
    assert source.index("THEN 'both'") < source.index("THEN 'sparse_only'")


def test_the_aggregate_is_windowed_like_the_other_summaries() -> None:
    """An all-time count would keep reporting the behaviour of a pipeline that
    has since been changed six times."""
    source = inspect.getsource(ops.retrieval_summary)
    assert source.count("make_interval(days => %s)") >= 4


def test_drop_reasons_stay_separate() -> None:
    """Three "dropped" outcomes are three different decisions — document cap,
    story fold, budget. Grouping them would make "which stage should I tune"
    unanswerable, which is the question this table exists for."""
    source = inspect.getsource(ops.retrieval_summary)
    assert "GROUP BY t.outcome" in source


def test_it_reports_how_deep_the_cited_evidence_sat_before_reranking() -> None:
    """If everything cited was already top-3 after fusion, the cross-encoder is
    not earning its 28% of the latency budget. Measured: median 8, and 56 of 141
    cited passages came from beyond fusion rank 10."""
    source = inspect.getsource(ops.retrieval_summary)
    assert "fused_rank" in source
    assert "percentile_cont" in source


def test_the_share_is_none_rather_than_zero_when_nothing_was_cited() -> None:
    """0.0 reads as "the sparse channel contributed nothing"; None reads as
    "there is no data yet". On a fresh deployment only one of those is true."""
    source = inspect.getsource(ops.retrieval_summary)
    assert "if cited else None" in source

"""Serve-time and backfilled groundedness (T2-4).

`rag_citation.support_score` was defined in V001 and filled by nothing until
2026-08-07: 560 rows, all NULL. The offline evaluation computed the number for
90 golden questions; the live path, which is what a reader looks at, never did.

The properties worth pinning are about what a missing score means and about
using one method rather than three.
"""

from __future__ import annotations

import inspect

from ahr.rag import support
from ahr.rag.eval import generation


def test_a_missing_score_means_unscored_not_unsupported() -> None:
    """A reranker outage would otherwise silently relabel every citation on the
    page as unsupported — a confident, wrong claim about the evidence."""
    source = inspect.getsource(support.score_citations)
    assert "return {}" in source
    # Failed pairs are dropped, never defaulted to a number.
    assert "continue" in source
    assert "0.0" not in source.split("scores: dict[str, float] = {}")[1]


def test_the_live_path_and_the_evaluation_share_a_threshold() -> None:
    """A citation the page calls supported must be one the report counted."""
    assert support.SUPPORT_THRESHOLD == generation.SUPPORT_THRESHOLD


def test_scoring_is_concurrent_rather_than_sequential() -> None:
    """The rerank API takes one query against many documents; support scoring is
    many queries against one document each, so it cannot be batched into a
    single request. Issued together the wall clock is one round trip — measured
    at 1514ms for four citations rather than four times that."""
    assert "asyncio.gather" in inspect.getsource(support.score_citations)


def test_the_backfill_selects_by_its_invariant_not_by_a_date() -> None:
    """A citation whose scoring failed at answer time is picked up on the next
    run, instead of staying NULL forever for not being in the original backlog.
    This project has been bitten before by work selected on someone else's
    state machine rather than on the invariant it maintains."""
    source = inspect.getsource(support.backfill)
    assert "support_score IS NULL" in source
    assert "created_at" not in source


def test_the_backfill_commits_per_batch() -> None:
    """An interrupted run should keep the scores it already paid for."""
    source = inspect.getsource(support.backfill)
    commit = source.index("connection.commit()")
    loop = source.index("for start in range(")
    assert loop < commit


def test_the_summary_reports_what_was_scored_not_just_a_mean() -> None:
    """A mean over one citation and a mean over ten are different claims."""
    summary = support.summarise({"a": 0.9, "b": 0.2}, citations=3)

    assert summary["scored"] == 2
    assert summary["citations"] == 3
    assert summary["support_supported"] == 0.5
    assert summary["support_min"] == 0.2


def test_no_scores_reports_no_mean_rather_than_zero() -> None:
    summary = support.summarise({}, citations=4)

    assert summary == {"scored": 0, "citations": 4}

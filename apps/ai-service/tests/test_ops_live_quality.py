"""The gate's metrics, recomputed over real traffic (`/eval` 线上实测).

The release gate reports over-refusal and citation support against 90 fixed
questions. That fixture is what makes rounds comparable and it is also the
whole of its blindness: a regression on a shape nobody wrote down has nothing
watching for it. These assertions pin the properties that make the live figures
readable *beside* the golden-set ones rather than confusable with them.
"""

from __future__ import annotations

import inspect

from ahr.rag import ops


def _code(function: object) -> str:
    """The function with its prose removed.

    These guards assert that a pattern is *absent*, and the comment explaining
    why it is absent has to quote it. Reading the whole source made both of
    those assertions fail against the very explanation of what they check.
    """
    source = inspect.getsource(function)  # type: ignore[arg-type]
    body = source[source.index('"""', source.index('"""') + 3) + 3 :]
    lines = [line.split("--")[0] for line in body.splitlines()]
    return "\n".join(line for line in lines if not line.strip().startswith("#"))


def test_the_support_threshold_is_the_evaluation_s_own() -> None:
    """A page that calls a citation supported must mean the threshold the
    evaluation counted against. Two constants that agree today are two
    constants that can disagree after one of them is tuned."""
    source = _code(ops.live_quality_summary)
    assert "from ahr.rag.support import SUPPORT_THRESHOLD" in source
    # And it reaches SQL as a parameter rather than as a literal.
    assert "c.support_score >= %s" in source
    assert "0.30" not in source and "0.3," not in source


def test_the_live_refusal_rate_is_not_called_the_gate_s_metric() -> None:
    """`over_refusal_rate` counts refusals of questions annotated answerable.
    Nothing annotates live traffic, so some of these refusals are correct.
    Sharing the name would invite a comparison the data cannot support."""
    source = _code(ops.live_quality_summary)
    assert '"refusalRate"' in source
    assert "over_refusal" not in source


def test_an_unrecorded_cache_outcome_is_not_counted_as_a_hit() -> None:
    """`IS DISTINCT FROM 'miss'` is true when the key is absent, so every
    answer written before cache metrics existed counted as a replay — 130 of
    241 against an actual 4. The measurement looked plausible and was wrong in
    the direction that flatters the cache."""
    source = _code(ops.live_quality_summary)
    assert "IS DISTINCT FROM 'miss'" not in source
    assert "->> 'outcome' IS NOT NULL" in source
    assert "->> 'outcome' <> 'miss'" in source


def test_every_rate_reports_none_rather_than_zero_on_an_empty_window() -> None:
    """A fresh deployment has no queries. Dividing to 0.0 would render as
    「误拒率 0%」 — a passing grade earned by having answered nothing."""
    source = _code(ops.live_quality_summary)
    assert "round(refused / total, 4) if total else None" in source
    assert "round(supported / scored, 4) if scored else None" in source


def test_an_answer_with_no_citation_is_counted_separately() -> None:
    """Not a refusal, not something the gate measures, and the one shape that
    looks like a normal answer while carrying nothing checkable."""
    source = _code(ops.live_quality_summary)
    assert '"answeredWithoutCitation"' in source
    assert "NOT EXISTS" in source


def test_the_window_is_bounded_by_the_same_interval_as_the_other_summaries() -> None:
    source = _code(ops.live_quality_summary)
    assert source.count("make_interval(days => %s)") == 4


def test_the_serving_model_is_reported_so_the_snapshot_can_be_checked() -> None:
    """The published snapshot names the model a round was measured on, and
    nothing compared it to the model answering. The page vouched for
    `deepseek-chat` while `deepseek-v4-flash` served every question."""
    source = _code(ops.live_quality_summary)
    assert "operation = 'rag_answer'" in source
    assert '"servingModel"' in source
    # By recency, not by volume: an evaluation sweep leaves hundreds of calls
    # behind, so the model being replaced outvotes its replacement for as long
    # as the window is wide — 469 against 22 when this was written.
    assert "ORDER BY max(created_at) DESC" in source
    assert "ORDER BY count(*) DESC" not in source


def test_the_stats_endpoint_serves_it() -> None:
    from ahr.rag import api

    source = _code(api.stats)
    assert "live_quality_summary" in source
    assert '"quality": live_quality_summary(connection, days=window)' in source

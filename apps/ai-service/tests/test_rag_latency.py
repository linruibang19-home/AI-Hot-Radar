"""Latency percentiles."""

from __future__ import annotations

from ahr.rag.eval.latency import Sample, percentile, summarise


def _sample(qid: str, category: str, total: int, **stages: int) -> Sample:
    return Sample(
        question_id=qid,
        category=category,
        total_ms=total,
        stages_ms=stages,
        prompt_tokens=1000,
        completion_tokens=200,
    )


def test_percentile_is_nearest_rank_not_interpolated() -> None:
    """An interpolated p95 is a number no request actually took.

    With two dozen samples that matters: the reported tail should be a real
    observation someone could have experienced.
    """
    values = [float(v) for v in range(1, 21)]
    assert percentile(values, 0.50) == 10.0
    assert percentile(values, 0.95) == 19.0
    assert percentile(values, 1.0) == 20.0


def test_percentile_of_a_single_sample_is_that_sample() -> None:
    assert percentile([7.0], 0.95) == 7.0


def test_percentile_of_nothing_is_zero_rather_than_an_error() -> None:
    # A stage that never ran (rerank when the provider is down) must not take
    # the whole report with it.
    assert percentile([], 0.95) == 0.0


def test_stage_shares_are_relative_to_the_end_to_end_mean() -> None:
    """The report has to say *where the budget goes*, not only how long each
    part takes — that is the question a tuning decision depends on."""
    samples = [
        _sample("q1", "fact_check", 1000, embed=100, generate=800),
        _sample("q2", "fact_check", 1000, embed=100, generate=800),
    ]
    stages = summarise(samples)["stages"]
    assert stages["generate"]["share"] == 0.8
    assert stages["embed"]["share"] == 0.1


def test_a_stage_missing_from_some_samples_is_averaged_over_the_rest() -> None:
    # `rerank` is absent when the provider is unavailable; averaging its
    # timings over runs that never performed it would understate the cost.
    samples = [
        _sample("q1", "x", 500, rerank=400),
        _sample("q2", "x", 100),
    ]
    stages = summarise(samples)["stages"]
    assert stages["rerank"]["mean_ms"] == 400


def test_summary_breaks_down_by_category() -> None:
    # recent_updates filters by time and retrieves less; explainer expands large
    # parents. One aggregate would hide that they are different workloads.
    samples = [
        _sample("q1", "recent_updates", 100),
        _sample("q2", "explainer", 900),
    ]
    by_category = summarise(samples)["by_category"]
    assert by_category["recent_updates"]["p50_ms"] == 100
    assert by_category["explainer"]["p50_ms"] == 900


def test_empty_input_reports_zero_samples() -> None:
    assert summarise([])["samples"] == 0

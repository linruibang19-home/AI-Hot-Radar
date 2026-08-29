"""A refusal records which mechanism produced it.

`refused` is a boolean covering three unrelated outcomes: the model declined,
the support gate removed every citation, or `drop_uncited_sentences` deleted
the last sentence that survived. All three emit the same sentence — 「检索到的
内容不足以回答这个问题」 — so a finished evaluation report showed a rate that
had moved and nothing about what moved it.

That cost a git bisect across a month of commits, twice, and the mechanism is
still not conclusively identified. These guards exist so the third time is a
report lookup.
"""

from __future__ import annotations

import inspect

from ahr.rag import service
from ahr.rag.eval import generation


def _refusal_block() -> str:
    source = inspect.getsource(service.answer_question)
    start = source.index("refused = not text or not citations")
    return source[start : source.index("check_invariants(", start)]


def test_the_three_mechanisms_are_told_apart() -> None:
    block = _refusal_block()
    for cause in ("all_sentences_uncited", "all_citations_unsupported", "model_declined"):
        assert cause in block, cause


def test_the_cause_is_decided_by_what_each_stage_actually_removed() -> None:
    """Not by re-inspecting the final text, which cannot distinguish "the model
    wrote nothing" from "everything it wrote was deleted"."""
    block = _refusal_block()
    assert "uncited_dropped and not text" in block
    assert "weak and not citations" in block


def test_the_other_refusal_exits_are_labelled_too() -> None:
    """Otherwise the two paths that already had distinct reasons would be the
    only ones missing from a breakdown of causes."""
    source = inspect.getsource(service.answer_question)
    assert '"invariant_violation"' in source
    assert '"credential_policy"' in source
    assert '"generation_unavailable"' in source


def test_a_provider_outage_is_not_filed_as_a_quality_result() -> None:
    """Measured the hard way. A run against an account with no balance left
    reported `over_refusal_rate` 1.0 across all 78 answerable questions — at a
    glance indistinguishable from the change under test having broken the
    pipeline, and worth a day of bisecting a defect that is not there."""
    source = inspect.getsource(generation)
    assert '"run_valid"' in source
    assert '"invalid_reason"' in source
    assert 'causes.get("generation_unavailable"' in source


def test_the_evaluation_carries_the_cause_through_to_the_report() -> None:
    fields = generation.GenerationResult.__dataclass_fields__
    assert "refusal_cause" in fields

    summarise = inspect.getsource(generation)
    assert '"over_refusal_causes"' in summarise
    # And the questions, so the next reader opens the report instead of paying
    # for another 90-question run to find out which ones refused.
    assert '"over_refused_questions"' in summarise


def test_an_unrecorded_cause_is_named_rather_than_dropped() -> None:
    """A refusal from a path that predates this labelling must still appear in
    the breakdown; silently omitting it would make the counts disagree with
    `over_refusal_rate` and look like a rounding artefact."""
    assert '"unrecorded"' in inspect.getsource(generation)


def test_a_cause_is_only_recorded_when_the_answer_was_refused() -> None:
    """`metrics` persists. A stale cause on an answered question would be read
    back later as a refusal that never happened."""
    source = inspect.getsource(generation)
    assert 'answer.metrics.get("refusal_cause") if answer.refused else None' in source

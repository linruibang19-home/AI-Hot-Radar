"""Serve-time and backfilled groundedness (T2-4).

`rag_citation.support_score` was defined in V001 and filled by nothing until
2026-08-07: 560 rows, all NULL. The offline evaluation computed the number for
90 golden questions; the live path, which is what a reader looks at, never did.

The properties worth pinning are about what a missing score means and about
using one method rather than three.
"""

from __future__ import annotations

import dataclasses
import inspect

from ahr.rag import support
from ahr.rag.answer import Citation, drop_citations
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


async def test_a_missing_claim_is_unscored_instead_of_using_the_question() -> None:
    class RecordingReranker:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def rerank(self, query: str, documents: list[str], *, top_n: int):
            self.queries.append(query)
            return [(0, 0.9)]

    citation = _citation(1, None)
    citation.claim_text = ""
    reranker = RecordingReranker()

    scores = await support.score_citations(reranker, [citation], {"chunk-1": "正文"})

    assert scores == {}
    assert reranker.queries == []


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


# --- Gating on the score (2026-08-09) -------------------------------------
#
# Until now the score decided nothing: an answer could show a source scored
# 0.000 beside one scored 0.998, both rendered identically. Live figures that
# set the shape of these tests, all measured before the change:
#
#     729 scored citations, 11.11% below threshold
#     denial answers   0.6465 mean, 29.41% weak
#     assertion answers 0.7577 mean, 10.22% weak
#     161 answered queries: 33 with a weak citation, 0 with nothing but weak


def _citation(number: int, score: float | None) -> Citation:
    return Citation(
        number=number,
        chunk_id=f"chunk-{number}",
        content_item_id=f"item-{number}",
        claim_text="Qwen3.8-Max 的参数量为 2.4 万亿。",
        title=f"标题 {number}",
        source_name="来源",
        canonical_url="https://example.com",
        published_at=None,
        support_score=score,
    )


def test_a_citation_below_the_threshold_is_dropped() -> None:
    """The live case this exists for: RAG-GOLD-076 carried three citations on
    one claim scoring 0.000 / 0.824 / 0.998, and showed all three."""
    citations = [_citation(1, 0.000), _citation(2, 0.824), _citation(3, 0.998)]
    assert support.unsupported_numbers(citations) == {1}


def test_an_unscored_citation_is_never_dropped() -> None:
    """`None` means the reranker did not answer, not that the passage failed."""
    citations = [_citation(1, None), _citation(2, 0.9)]
    assert support.unsupported_numbers(citations) == set()


def test_the_list_is_never_emptied() -> None:
    """Dropping the last citation would reach `check_invariants` and become a
    refusal. Grounded denials are the answers most exposed to that — 29.41% of
    their citations score weak — and turning one back into a dead-end refusal
    is the regression this guard exists to prevent."""
    citations = [_citation(1, 0.05), _citation(2, 0.20), _citation(3, 0.01)]
    dropped = support.unsupported_numbers(citations)

    assert 2 not in dropped, "the strongest citation must survive"
    assert dropped == {1, 3}
    assert len(citations) - len(dropped) == 1


def test_dropping_renumbers_the_body_so_no_marker_dangles() -> None:
    """Leaving `[3]` in the prose after removing `[2]` fails invariant 1, which
    would convert a repairable answer into a refusal."""
    citations = [_citation(1, 0.9), _citation(2, 0.05), _citation(3, 0.8)]
    text, kept, limitations = drop_citations(
        "结论 [1]，还有细节 [2]，以及 [3]。", citations, [], drop={2}
    )

    assert text == "结论 [1]，还有细节 ，以及 [2]。"
    assert [c.number for c in kept] == [1, 2]
    assert [c.chunk_id for c in kept] == ["chunk-1", "chunk-3"]
    assert limitations == []


def test_dropping_renumbers_limitations_too() -> None:
    """Same rule in both fields: a number meaning nothing to the reader must
    not survive in one because the cleaning was written for the other."""
    citations = [_citation(1, 0.05), _citation(2, 0.9)]
    _text, _kept, limitations = drop_citations(
        "结论 [2]。", citations, ["证据 [1] 只覆盖了一部分", "另一条限定"], drop={1}
    )

    assert limitations == ["证据  只覆盖了一部分", "另一条限定"]


def test_nothing_weak_changes_nothing() -> None:
    citations = [_citation(1, 0.9), _citation(2, 0.8)]
    assert support.unsupported_numbers(citations) == set()

    text, kept, limitations = drop_citations("结论 [1][2]。", citations, ["限定"], drop=set())
    assert text == "结论 [1][2]。"
    assert [c.number for c in kept] == [1, 2]
    assert limitations == ["限定"]


def test_the_served_path_scores_before_it_checks_invariants() -> None:
    """A score that arrives after the decision it should inform is decoration.

    This is the project's recurring failure shape — evaluated, reported, marked
    done, never wired — so the ordering is pinned rather than trusted.
    """
    from ahr.rag import service

    # Call sites, not mentions: the prose above the call names both functions,
    # and matching that would pin the comment rather than the order of work.
    source = inspect.getsource(service.answer_question)
    assert source.index("score_citations(") < source.index("unsupported_numbers(")
    assert source.index("unsupported_numbers(") < source.index("check_invariants(")


def test_the_served_path_never_turns_a_drop_into_a_refusal() -> None:
    """`refused` is decided from the bound citations, before any is removed."""
    from ahr.rag import service

    source = inspect.getsource(service.answer_question)
    assert source.index("refused = not text or not citations") < source.index("score_citations")


def test_the_report_keeps_both_scoring_bases_apart() -> None:
    """Gating on a number turns that number into a tautology.

    Every citation the gate lets through scored above threshold *on the parent
    block*, so `support_as_read_supported` can only report what the gate already
    enforced — the same trap as a system that refuses everything and scores
    perfectly on abstention. The passage-level `support_supported` is the one
    that can still fail, and it carries the historical series, so both are
    reported and neither is renamed into the other.
    """
    from ahr.rag.eval import generation

    fields = {f.name for f in dataclasses.fields(generation.GenerationResult)}
    assert {"support_mean", "support_supported"} <= fields
    assert {"support_as_read_mean", "support_as_read_supported"} <= fields

    summary = generation.summarise(
        [
            generation.GenerationResult(
                question_id="q",
                category="fact_check",
                answerable=True,
                refused=False,
                citations=2,
                support_mean=0.5,
                support_supported=0.5,
                support_as_read_mean=0.9,
                support_as_read_supported=1.0,
            )
        ]
    )["overall"]

    assert summary["support_supported"] == 0.5
    assert summary["support_as_read_supported"] == 1.0


def test_the_evaluation_widens_passages_exactly_as_the_server_does() -> None:
    """A different truncation would make this a third basis rather than the
    one the gate judged, and the two numbers would stop being comparable for a
    reason nobody would think to look for."""
    from ahr.rag.eval import generation

    source = inspect.getsource(generation._load_parent_passages)
    assert "MAX_PARENT_CHARS" in source
    assert "expand" in source


# --- Phase A: retrieval-confidence signal ---------------------------------


def test_a_mostly_dropped_answer_is_flagged_weak() -> None:
    """The live failure: 「智谱最近发布了什么」 dropped 8 of 9 citations and then
    stated with the survivor that Zhipu had released nothing — while the window
    held three Zhipu items. The collapse was visible and spent on small print."""
    assert support.is_weak_retrieval(dropped=8, kept=1) is True


def test_a_healthy_answer_is_not_flagged() -> None:
    """The probe's good answers dropped 0 or 2 of 7-10. The gap to the bad ones
    is wide, which is what makes a threshold defensible at all."""
    assert support.is_weak_retrieval(dropped=0, kept=10) is False
    assert support.is_weak_retrieval(dropped=2, kept=8) is False


def test_nothing_scored_is_not_weak() -> None:
    """A reranker outage scores nothing. That is missing information, not a
    verdict about the evidence — the same rule as an unscored citation."""
    assert support.is_weak_retrieval(dropped=0, kept=0) is False


def test_the_flag_never_becomes_a_refusal() -> None:
    """Over-refusal is measured at 0.0000 and was reached by undoing a
    regression. Whether a high drop rate predicts a wrong answer is an unmeasured
    correlation, and acting on it before measuring is how that regression
    happened the first time."""
    from ahr.rag import service

    # The precise property, not "no refusal appears after this point": the
    # invariant check downstream still refuses, and should. What must never
    # happen is `weak_retrieval` participating in that decision.
    source = inspect.getsource(service.answer_question)
    for line in source.splitlines():
        if "weak_retrieval" in line:
            assert "refused" not in line, line
            assert "refusal_reason" not in line, line

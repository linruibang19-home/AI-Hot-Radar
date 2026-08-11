"""The retrieval trace: why *these* passages and not the others (T1-1).

The pipeline computed all of this already and dropped it at every hand-off.
What is worth pinning is that the trace stays a pure observer — a wrong trace
must be able to make the explanation wrong without making the answer wrong —
and that the elimination reasons are reported by the code that makes the
decision rather than reconstructed afterwards from positions, which would be a
guess presented as an explanation.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from ahr.rag import service
from ahr.rag.folding import ChunkFacts, fold_by_story
from ahr.rag.trace import (
    CITED,
    DROPPED_BUDGET,
    DROPPED_STORY_FOLD,
    EVIDENCE_UNCITED,
    RANKED_OUT,
    TRACE_LIMIT,
    RetrievalTrace,
)


@dataclass
class _Hit:
    chunk_id: str
    content_item_id: str = "item"
    score: float = 0.5
    channels: tuple[str, ...] = ()
    boosts: tuple[str, ...] = ()


def _hits(*ids: str) -> list[_Hit]:
    return [_Hit(chunk_id=i) for i in ids]


# --- the funnel is recorded at every stage ---------------------------------


def test_a_passage_found_by_only_one_channel_says_so() -> None:
    """The MXFP4 case, made visible. A passage the dense channel never returned
    and the keyword channel ranked first is the entire argument for hybrid
    retrieval, and until now it left no trace anywhere."""
    trace = RetrievalTrace()
    trace.record_channel("dense", _hits("a", "b"))
    trace.record_channel("sparse", _hits("c", "a"))

    only_sparse = trace.candidates["c"]
    assert only_sparse.dense_rank is None
    assert only_sparse.sparse_rank == 1

    both = trace.candidates["a"]
    assert (both.dense_rank, both.sparse_rank) == (1, 2)


def test_fusion_records_the_provenance_that_fusedhit_already_carried() -> None:
    trace = RetrievalTrace()
    trace.record_fusion(
        [_Hit(chunk_id="a", channels=("dense", "sparse"), boosts=("primary", "in_window"))]
    )

    candidate = trace.candidates["a"]
    assert candidate.channels == "dense+sparse"
    assert candidate.boosts == "primary,in_window"
    assert candidate.fused_rank == 1


def test_the_reranker_rescuing_a_passage_is_visible_as_a_rank_change() -> None:
    """The one thing B4 is famous for inside this project. Without both ranks
    stored there is no way to see it happen on a real question."""
    trace = RetrievalTrace()
    trace.record_fusion(_hits("a", "b", "c"))
    trace.record_rerank(_hits("c", "a", "b"))

    rescued = trace.candidates["c"]
    assert (rescued.fused_rank, rescued.rerank_rank) == (3, 1)


# --- the elimination reasons -----------------------------------------------


def test_folding_reports_why_it_dropped_each_passage() -> None:
    """Reported by the loop that decides, not inferred by the caller."""
    facts = {
        "a": ChunkFacts("a", "i1", "story-1", "src-1", "primary"),
        "b": ChunkFacts("b", "i2", "story-1", "src-1", "secondary"),
        "c": ChunkFacts("c", "i3", None, "src-2", "secondary"),
    }
    reasons: dict[str, str] = {}
    kept = fold_by_story(["a", "b", "c"], facts, limit=5, reasons=reasons)

    # `b` is the same outlet on the same event: no independent confirmation.
    assert kept == ["a", "c"]
    assert reasons["b"] == "story_fold"


def test_running_out_of_budget_is_not_reported_as_folding() -> None:
    """They look identical in the answer and mean opposite things: one says an
    event was over-represented, the other says the evidence set filled up."""
    facts = {
        name: ChunkFacts(name, f"i-{name}", None, f"src-{name}", "secondary")
        for name in ("a", "b", "c")
    }
    reasons: dict[str, str] = {}
    kept = fold_by_story(["a", "b", "c"], facts, limit=2, reasons=reasons)

    assert kept == ["a", "b"]
    assert reasons["c"] == "budget"
    assert "story_fold" not in reasons.values()


def test_selection_translates_the_reasons_without_inventing_any() -> None:
    source = inspect.getsource(service.select_evidence)
    # The reasons come from `fold_by_story`; an earlier version reconstructed
    # them from list positions, which was a guess dressed as an explanation.
    assert "reasons=fold_reasons" in source
    assert "DROPPED_STORY_FOLD" in source and "DROPPED_BUDGET" in source
    # The distinction is carried through rather than collapsed into one label.
    assert DROPPED_STORY_FOLD != DROPPED_BUDGET


# --- outcomes and what gets stored -----------------------------------------


def test_a_cited_passage_outranks_its_earlier_label() -> None:
    trace = RetrievalTrace()
    trace.record_fusion(_hits("a", "b"))
    trace.record_outcomes({"a": EVIDENCE_UNCITED, "b": EVIDENCE_UNCITED})
    trace.mark_cited(["a"])

    assert trace.candidates["a"].outcome == CITED
    assert trace.candidates["b"].outcome == EVIDENCE_UNCITED


def test_storage_is_bounded_to_the_candidates_that_were_in_contention() -> None:
    trace = RetrievalTrace()
    trace.record_fusion(_hits(*[f"c{i}" for i in range(200)]))

    assert len(trace.rows()) == TRACE_LIMIT


def test_a_survivor_is_kept_even_when_fusion_ranked_it_out_of_the_window() -> None:
    """This combination is the interesting one — it is what a reranker rescue
    looks like — and a plain top-40 cut would delete exactly those rows."""
    trace = RetrievalTrace()
    trace.record_fusion(_hits(*[f"c{i}" for i in range(200)]))
    trace.mark_cited(["c150"])

    stored = {row.chunk_id for row in trace.rows()}
    assert "c150" in stored
    assert len(stored) == TRACE_LIMIT + 1


def test_an_untouched_candidate_defaults_to_ranked_out() -> None:
    trace = RetrievalTrace()
    trace.record_fusion(_hits("a"))
    assert trace.candidates["a"].outcome == RANKED_OUT


# --- the observer never decides --------------------------------------------


def test_nothing_in_the_pipeline_reads_the_trace_back() -> None:
    """The trace is written to and never consulted. That asymmetry is what
    makes it safe: a defect here can only produce a wrong explanation, never a
    wrong answer."""
    source = inspect.getsource(service)
    body = source[source.index("async def retrieve(") : source.index("def select_evidence(")]

    for line in body.splitlines():
        stripped = line.strip()
        if "trace" not in stripped or stripped.startswith("#"):
            continue
        # Only guards, the parameter itself, and record_* calls are allowed.
        assert (
            stripped.startswith("if trace is not None")
            or "trace.record_" in stripped
            or "trace:" in stripped
            or "trace=" in stripped
            or "`trace`" in stripped
        ), stripped


def test_a_failed_trace_write_does_not_lose_the_answer() -> None:
    source = inspect.getsource(service.answer_question)
    persisted = source.index("persist_trace(")
    guarded = source[persisted - 400 : persisted + 300]

    assert "try:" in guarded
    assert "rollback" in guarded
    # And it happens after the answer itself is committed.
    assert source.index("_persist(connection, result)") < persisted

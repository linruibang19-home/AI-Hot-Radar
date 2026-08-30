"""Mining real traffic for the questions worth annotating next.

The frozen 90-question set can show that retrieval and citation mechanics have
not regressed. It cannot show that answers over the two thirds of the corpus
ingested after its cutoff are right, and inventing more questions by hand would
reproduce the blind spot that created the gap — the cases someone thinks to
write are the ones they already have in mind.

Real questions do not have that bias and arrive pre-judged: a citation the
cross-encoder scored below the support threshold is one the pipeline itself
called too weak. What this must never do is finish the job — the annotation is
the part that has to stay human.
"""

from __future__ import annotations

import inspect

from ahr.rag.eval import candidates
from ahr.rag.eval.candidates import BANDS, Candidate, _band
from ahr.rag.support import SUPPORT_THRESHOLD


def _candidate(band: str, worst: float | None = None) -> Candidate:
    return Candidate(
        query_id="q", question="Q", band=band, asked_at=None, worst_support=worst, citations=1
    )


# --- which band a question lands in ---------------------------------------


def test_a_citation_below_the_threshold_outranks_every_other_reason() -> None:
    """The pipeline already judged that passage too weak for the sentence
    attached to it. That is a labelled hard case, for free."""
    assert _band(False, 3, SUPPORT_THRESHOLD - 0.01, False) == "weak_support"
    # And it wins even when the question also qualifies as a refusal.
    assert _band(True, 3, 0.1, True) == "weak_support"


def test_a_refusal_is_a_candidate_whichever_way_it_was_right() -> None:
    """A correct refusal becomes an abstention question; an incorrect one
    becomes exactly the over-refusal case the gate watches for."""
    assert _band(True, 0, None, False) == "refused"


def test_an_answer_with_no_citation_is_its_own_band() -> None:
    """Not a refusal, and shaped like a normal answer while carrying nothing
    checkable — the one failure the gate has no metric for."""
    assert _band(False, 0, None, False) == "uncited"


def test_evidence_the_frozen_corpus_cannot_contain_is_a_candidate() -> None:
    assert _band(False, 2, 0.9, True) == "new_source"


def test_a_healthy_question_is_not_a_candidate() -> None:
    """Annotating answers that already worked spends the scarce resource — a
    human hour — on the cases that teach least."""
    assert _band(False, 2, 0.9, False) is None


# --- what the shortlist guarantees ----------------------------------------


def test_the_threshold_is_the_evaluation_s_own() -> None:
    """A candidate called weakly-supported must mean the threshold the gate
    counted against; a second constant would drift."""
    source = inspect.getsource(candidates)
    assert "from ahr.rag.support import SUPPORT_THRESHOLD" in source
    assert "0.30" not in source


def test_bands_are_ordered_most_diagnostic_first() -> None:
    assert BANDS[0] == "weak_support"
    assert set(BANDS) == {"weak_support", "refused", "uncited", "new_source"}


def test_a_question_asked_twice_appears_once() -> None:
    """Real traffic repeats. Two rows of the same question are one annotation
    job, and listing it twice would spend the budget on a duplicate."""
    source = inspect.getsource(candidates.mine)
    assert "if band is None or question in seen" in source
    assert "seen.add(question)" in source


def test_retrieved_documents_are_not_offered_as_the_answer() -> None:
    """Pre-filling `relevant_items` with what the pipeline retrieved would turn
    annotation into agreeing with the system under test — the field is named
    `retrieved` for that reason, and the note says so."""
    source = inspect.getsource(candidates)
    assert "retrieved" in source
    assert "relevant_items=" not in source
    result_note = inspect.getsource(candidates.mine)
    assert "候选清单，不是黄金集" in result_note


def test_the_golden_set_s_own_replays_are_not_mined_as_new_traffic() -> None:
    """Every evaluation run pushes the 90 questions through the pipeline and
    writes them to `rag_query` — 71 of 247 rows. Left in, the miner reads the
    set back to itself: six of the first thirty shortlisted were already
    annotated, two of them abstention questions whose low support score was the
    system refusing correctly."""
    source = inspect.getsource(candidates.mine)
    assert "exclude_questions" in source
    assert "question.strip() in exclude_questions" in source or (
        "question.strip()" in source and "exclude_questions" in source
    )
    # Reported, not silently dropped: a shortlist that shrank because the week
    # was quiet and one that shrank because it was all replays look identical.
    assert "golden_replays_skipped" in source


def test_the_command_feeds_the_miner_the_real_golden_set() -> None:
    """Hardcoding the exclusions, or defaulting them to empty, would let the
    contamination back in the moment a question is added to the set."""
    from ahr import cli

    source = inspect.getsource(cli.cmd_golden_candidates)
    assert "load_golden_set" in source
    assert "exclude_questions=replayed" in source


def test_mining_never_writes() -> None:
    """It reads traffic to propose work. A miner that could edit the golden set
    is a miner that can quietly grade its own homework."""
    source = inspect.getsource(candidates)
    for statement in ("INSERT", "UPDATE ", "DELETE", "commit()"):
        assert statement not in source


def test_the_command_stops_at_a_shortlist() -> None:
    from ahr import cli

    source = inspect.getsource(cli.cmd_golden_candidates)
    assert "mine(" in source
    # No annotation, no writing into data/golden.
    assert "data/golden" not in source

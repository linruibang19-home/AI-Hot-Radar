"""Generation-side quality metrics."""

from ahr.rag.eval.generation import GenerationResult, citation_coverage, summarise


def test_citation_after_terminal_punctuation_belongs_to_the_sentence() -> None:
    assert citation_coverage("GLM-5.2 已上线。[1]") == 1.0
    assert citation_coverage("GLM-5.2 已上线[1]。") == 1.0


def test_a_following_uncited_sentence_still_reduces_coverage() -> None:
    assert citation_coverage("GLM-5.2 已上线。[1] 第二句没有引用。") == 0.5


def test_refusal_is_measured_by_over_refusal_not_citation_completeness() -> None:
    answered = GenerationResult(
        question_id="ok",
        category="fact_check",
        answerable=True,
        refused=False,
        citations=1,
        citation_coverage=1.0,
    )
    refused = GenerationResult(
        question_id="miss",
        category="fact_check",
        answerable=True,
        refused=True,
        citations=0,
        citation_coverage=0.0,
    )
    overall = summarise([answered, refused])["overall"]
    assert overall["citation_coverage"] == 1.0
    assert overall["over_refusal_rate"] == 0.5
    assert overall["answered"] == 1

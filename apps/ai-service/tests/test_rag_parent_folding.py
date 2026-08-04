"""Parent-block ladder (B5) and story folding (B6)."""

from __future__ import annotations

from ahr.rag.folding import ChunkFacts, fold_by_story, main_source_first
from ahr.rag.parent import PARENT_BUDGET_TOKENS, choose_tier

# --------------------------------------------------------------------------
# B5: which granularity the ladder lands on
# --------------------------------------------------------------------------


def test_a_document_that_fits_is_taken_whole() -> None:
    # 69.3% of this corpus lands here, which is why the section level is not
    # the default: for most documents it is an abstraction nobody needs.
    assert choose_tier(document_tokens=900, section_tokens=400) == "document"


def test_a_long_document_falls_back_to_its_section() -> None:
    assert choose_tier(document_tokens=8000, section_tokens=1200) == "section"


def test_a_chunk_without_a_heading_skips_the_section_tier() -> None:
    """33.5% of chunks carry no heading at all.

    A fixed "section = parent" is undefined for them; the ladder must drop
    straight to neighbours rather than produce nothing.
    """
    assert choose_tier(document_tokens=8000, section_tokens=None) == "neighbours"


def test_an_oversized_section_also_falls_through() -> None:
    # The 90th percentile section is 3519 tokens — promoting it whole would
    # blow the budget the ladder exists to respect.
    assert choose_tier(document_tokens=30000, section_tokens=3519) == "neighbours"


def test_the_budget_is_the_boundary_not_a_suggestion() -> None:
    budget = PARENT_BUDGET_TOKENS
    assert choose_tier(document_tokens=budget, section_tokens=None) == "document"
    assert choose_tier(document_tokens=budget + 1, section_tokens=budget) == "section"
    assert choose_tier(document_tokens=budget + 1, section_tokens=budget + 1) == "neighbours"


# --------------------------------------------------------------------------
# B6: story folding
# --------------------------------------------------------------------------


def _facts(*rows: tuple[str, str, str | None, str, str]) -> dict[str, ChunkFacts]:
    return {
        chunk: ChunkFacts(
            chunk_id=chunk,
            content_item_id=item,
            story_id=story,
            source_id=source,
            source_tier=tier,
        )
        for chunk, item, story, source, tier in rows
    }


def test_one_event_reported_by_four_outlets_keeps_three() -> None:
    """The Anthropic incident, exactly as the smoke test found it.

    Four outlets covering one disclosure is corroboration, not four facts;
    §7 keeps one main source plus two corroborating ones.
    """
    facts = _facts(
        ("c1", "i1", "s-anthropic", "simonwillison", "expert"),
        ("c2", "i2", "s-anthropic", "arstechnica", "secondary"),
        ("c3", "i3", "s-anthropic", "theverge", "secondary"),
        ("c4", "i4", "s-anthropic", "qbitai", "secondary"),
    )
    kept = fold_by_story(["c1", "c2", "c3", "c4"], facts, limit=10)
    assert kept == ["c1", "c2", "c3"]


def test_two_articles_from_the_same_outlet_count_once() -> None:
    # Independence is per source, not per article: the same outlet writing
    # twice adds no confirmation.
    facts = _facts(
        ("c1", "i1", "s1", "theverge", "secondary"),
        ("c2", "i2", "s1", "theverge", "secondary"),
        ("c3", "i3", "s1", "arstechnica", "secondary"),
    )
    assert fold_by_story(["c1", "c2", "c3"], facts, limit=10) == ["c1", "c3"]


def test_chunks_without_a_story_are_untouched() -> None:
    """Most releases genuinely have one source. Folding must not thin out a
    result set that has nothing to fold."""
    facts = _facts(
        ("c1", "i1", None, "llamacpp", "primary"),
        ("c2", "i2", None, "vllm", "primary"),
        ("c3", "i3", None, "sglang", "primary"),
    )
    assert fold_by_story(["c1", "c2", "c3"], facts, limit=10) == ["c1", "c2", "c3"]


def test_folding_frees_slots_for_other_events() -> None:
    # The point of folding: what the dropped duplicates make room for.
    facts = _facts(
        ("a1", "i1", "sA", "one", "secondary"),
        ("a2", "i2", "sA", "two", "secondary"),
        ("a3", "i3", "sA", "three", "secondary"),
        ("a4", "i4", "sA", "four", "secondary"),
        ("b1", "i5", "sB", "five", "primary"),
    )
    kept = fold_by_story(["a1", "a2", "a3", "a4", "b1"], facts, limit=4)
    assert "b1" in kept
    assert len([c for c in kept if c.startswith("a")]) == 3


def test_retrieval_order_survives_folding() -> None:
    facts = _facts(
        ("c1", "i1", None, "x", "secondary"),
        ("c2", "i2", None, "y", "secondary"),
    )
    assert fold_by_story(["c2", "c1"], facts, limit=10) == ["c2", "c1"]


def test_unknown_chunks_are_dropped_rather_than_crashing() -> None:
    facts = _facts(("c1", "i1", None, "x", "primary"))
    assert fold_by_story(["c1", "missing"], facts, limit=10) == ["c1"]


# --------------------------------------------------------------------------
# main source ordering
# --------------------------------------------------------------------------


def test_the_first_hand_source_leads_within_a_story() -> None:
    """§8: a fact-check answer leads with a first-hand source where one exists."""
    facts = _facts(
        ("c1", "i1", "s1", "theverge", "secondary"),
        ("c2", "i2", "s1", "anthropic", "primary"),
    )
    assert main_source_first(["c1", "c2"], facts) == ["c2", "c1"]


def test_ordering_between_different_events_is_left_alone() -> None:
    # Only the order *inside* a story changes; relevance decides which event
    # comes first, and the reranker already judged that.
    facts = _facts(
        ("a1", "i1", "sA", "theverge", "secondary"),
        ("b1", "i2", "sB", "anthropic", "primary"),
    )
    assert main_source_first(["a1", "b1"], facts) == ["a1", "b1"]

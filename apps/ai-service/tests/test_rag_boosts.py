"""§6's entity-subject boost and repost penalty.

Both were recorded as "data not available" and shipped as unimplemented. That
was wrong: `item_entity.role` distinguishes subject from mention (1848 subject
rows), and near-duplicate detection already sets `duplicate_of_id` (516 chunks
in the index belong to copies). The claim was never checked against the schema.

These are the last two of the five adjustments §6 specifies, so the tests that
matter are about their *bounds* — B3's first run turned ±0.05 into the ranking
function by applying it to scores whose entire spread was 0.008.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ahr.rag.fusion import (
    BOOST_ENTITY_SUBJECT,
    BOOST_PRIMARY_SOURCE,
    PENALTY_OPINION_FOR_FACT,
    PENALTY_REPOST,
    FusedHit,
    apply_boosts,
)


def _hit(item: str, score: float) -> FusedHit:
    return FusedHit(
        chunk_id=f"c-{item}",
        content_item_id=item,
        score=score,
        title=f"title {item}",
        source_name="src",
        channels=("dense",),
    )


def _meta(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source_tier": "secondary",
        "content_type": "news",
        "published_at": datetime(2026, 8, 1, tzinfo=UTC),
        "is_repost": False,
        "subject_entities": frozenset(),
    }
    base.update(overrides)
    return base


# --- entity subject --------------------------------------------------------


def test_an_item_whose_subject_is_the_asked_entity_is_promoted() -> None:
    """§6: 直接命中目标实体为主语 +0.05.

    A release note whose subject is the model being asked about answers the
    question; one that lists it among supported formats mentions it.
    """
    hits = [_hit("mentions", 1.0), _hit("subject", 1.0)]
    metadata = {
        "mentions": _meta(subject_entities=frozenset({"other"})),
        "subject": _meta(subject_entities=frozenset({"kimi"})),
    }

    ordered = apply_boosts(
        hits, metadata, query_type="fact_check", window=None, query_entities=frozenset({"kimi"})
    )
    assert ordered[0].content_item_id == "subject"
    assert "entity_subject" in ordered[0].boosts


def test_no_resolved_entity_means_no_boost_for_anyone() -> None:
    """A question naming nothing the corpus knows must not silently promote
    whichever documents happen to carry subject annotations."""
    hits = [_hit("a", 1.0), _hit("b", 0.9)]
    metadata = {
        "a": _meta(subject_entities=frozenset({"x"})),
        "b": _meta(subject_entities=frozenset({"y"})),
    }

    ordered = apply_boosts(
        hits, metadata, query_type="explainer", window=None, query_entities=frozenset()
    )
    assert all("entity_subject" not in hit.boosts for hit in ordered)


def test_an_entity_present_only_as_a_mention_earns_nothing() -> None:
    # `load_item_metadata` only aggregates role='subject', so a mention simply
    # never reaches this table. Pinned because widening that query would
    # silently turn the boost into "appears anywhere".
    hits = [_hit("a", 1.0)]
    metadata = {"a": _meta(subject_entities=frozenset())}

    ordered = apply_boosts(
        hits, metadata, query_type="fact_check", window=None, query_entities=frozenset({"kimi"})
    )
    assert ordered[0].boosts == ()


# --- repost ----------------------------------------------------------------


def test_a_near_duplicate_is_demoted_below_its_original() -> None:
    hits = [_hit("copy", 1.0), _hit("original", 1.0)]
    metadata = {"copy": _meta(is_repost=True), "original": _meta()}

    ordered = apply_boosts(hits, metadata, query_type="fact_check", window=None)
    assert ordered[0].content_item_id == "original"
    assert "repost" in ordered[1].boosts


def test_a_repost_is_demoted_not_removed() -> None:
    """Still evidence if the original is missing from the candidate set — and
    it often is, since the two rank independently."""
    hits = [_hit("copy", 1.0)]
    metadata = {"copy": _meta(is_repost=True)}

    ordered = apply_boosts(hits, metadata, query_type="fact_check", window=None)
    assert len(ordered) == 1


# --- bounds ----------------------------------------------------------------


def test_every_adjustment_stays_within_the_magnitudes_section_6_fixes() -> None:
    assert BOOST_ENTITY_SUBJECT == 0.05
    assert PENALTY_REPOST == -0.10


def test_the_adjustments_cannot_outweigh_the_full_relevance_range() -> None:
    """Applied to a score normalised onto [0, 1]. The worst case — every
    penalty at once — must not exceed the spread it is adjusting, or metadata
    becomes the ranking function, which is exactly what happened in B3."""
    worst = abs(PENALTY_REPOST) + abs(PENALTY_OPINION_FOR_FACT)
    best = BOOST_PRIMARY_SOURCE + BOOST_ENTITY_SUBJECT
    assert worst < 1.0
    assert best < 1.0


def test_a_clearly_more_relevant_passage_survives_every_penalty() -> None:
    hits = [_hit("relevant", 10.0), _hit("boosted", 0.0)]
    metadata = {
        "relevant": _meta(is_repost=True, content_type="opinion"),
        "boosted": _meta(source_tier="primary", subject_entities=frozenset({"kimi"})),
    }

    ordered = apply_boosts(
        hits, metadata, query_type="fact_check", window=None, query_entities=frozenset({"kimi"})
    )
    assert ordered[0].content_item_id == "relevant"


def test_each_signal_is_counted_once() -> None:
    """§6 forbids double-counting; boost stacking is how metadata quietly
    becomes the ranking function."""
    hits = [_hit("a", 1.0)]
    metadata = {
        "a": _meta(
            source_tier="primary",
            is_repost=True,
            subject_entities=frozenset({"kimi"}),
            content_type="opinion",
        )
    }

    ordered = apply_boosts(
        hits, metadata, query_type="fact_check", window=None, query_entities=frozenset({"kimi"})
    )
    assert len(ordered[0].boosts) == len(set(ordered[0].boosts))

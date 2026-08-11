"""Topic normalisation and editorial selection tests (M2)."""

from __future__ import annotations

import inspect
from typing import get_args

import pytest

from ahr.processing.schemas import ContentType
from ahr.processing.selection import (
    CONTENT_TYPE_WEIGHT,
    DAILY_QUOTA,
    MAX_PER_SOURCE_PER_DAY,
    score_item,
)
from ahr.processing.topics import known_slugs, normalize_slug, resolve

VOCABULARY = {
    "models",
    "llm",
    "multimodal",
    "reasoning",
    "image",
    "video",
    "audio",
    "engineering",
    "agent",
    "rag",
    "mcp",
    "evaluation",
    "inference",
    "fine_tuning",
    "safety",
    "observability",
    "ecosystems",
    "java_ai",
    "spring_ai",
    "python_ai",
    "ai_coding",
    "open_source",
    "business",
    "funding",
    "regulation",
    "chips",
    "research",
}


# --- topic normalisation -------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("RAG", "rag"),
        ("Retrieval Augmented Generation", "retrieval_augmented_generation"),
        ("fine-tuning", "fine_tuning"),
        ("  Agent  ", "agent"),
    ],
)
def test_normalize_slug(raw: str, expected: str) -> None:
    assert normalize_slug(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("agent", "agent"),
        ("agents", "agent"),
        ("Agentic", "agent"),
        ("Retrieval Augmented Generation", "rag"),
        ("vector search", "rag"),
        ("Model Context Protocol", "mcp"),
        ("LLMs", "llm"),
        ("RLHF", "fine_tuning"),
        ("benchmark", "evaluation"),
        ("GPU", "chips"),
        ("alignment", "safety"),
    ],
)
def test_aliases_collapse_onto_canonical_topics(raw: str, expected: str) -> None:
    """Without this the topic pages fragment into near-duplicate slugs."""
    assert resolve(raw, VOCABULARY) == expected


@pytest.mark.parametrize("raw", ["", "   ", "completely_made_up_topic", "!!!"])
def test_unknown_labels_are_dropped(raw: str) -> None:
    """AHR-DATA-300 §7: an unmapped label must not create a new topic."""
    assert resolve(raw, VOCABULARY) is None


def test_known_slugs_offers_leaves_only_never_a_group_name() -> None:
    """A group is a place to put topics, not a topic.

    This test used to assert the opposite, and so pinned the defect instead of
    catching it: group keys were offered to the extraction step, and 23 items
    ended up tagged `business` — a bucket the topic map renders as a section
    heading rather than a card, leaving those items reachable from nowhere.
    """
    taxonomy = {"tech": ["llm", "multimodal"], "industry": ["funding"]}

    assert known_slugs(taxonomy) == {"llm", "multimodal", "funding"}
    assert resolve("tech", known_slugs(taxonomy)) is None


def test_a_retired_topic_resolves_to_the_one_that_absorbed_it() -> None:
    """The merges are in the alias table as well as in the migration, so a
    label extracted tomorrow lands where yesterday's tags were moved to."""
    vocabulary = {"ai_coding", "inference", "rag", "enterprise"}

    assert resolve("spring_ai", vocabulary) == "ai_coding"
    assert resolve("observability", vocabulary) == "inference"
    assert resolve("embedding", vocabulary) == "rag"
    assert resolve("business", vocabulary) == "enterprise"


# --- selection scoring ---------------------------------------------------


def _score(**overrides: object) -> float:
    base: dict[str, object] = {
        "quality_score": 70.0,
        "source_tier": "primary",
        "content_type": "model_release",
        "age_hours": 1.0,
        "body_chars": 4000,
        "independent_sources": 1,
    }
    base.update(overrides)
    return score_item(**base).total()  # type: ignore[arg-type]


def test_primary_source_outranks_community() -> None:
    assert _score(source_tier="primary") > _score(source_tier="community")


def test_release_outranks_opinion() -> None:
    assert _score(content_type="model_release") > _score(content_type="opinion")


def test_fresh_outranks_stale() -> None:
    assert _score(age_hours=1) > _score(age_hours=60)


def test_substantial_body_outranks_thin_one() -> None:
    assert _score(body_chars=4000) > _score(body_chars=200)


def test_unenriched_content_still_scores() -> None:
    """The homepage must not go empty when the model is unavailable."""
    assert _score(quality_score=None, content_type=None) > 0


def test_corroborated_event_outranks_an_identical_single_source_item() -> None:
    """The gap M3 exists to close.

    Before this factor the shortlist could not see corroboration at all: the two
    events that four and three independent outlets reported were selected zero
    times, while 87 single-source release notes were.
    """
    assert _score(independent_sources=4) > _score(independent_sources=1)


def test_corroboration_saturates() -> None:
    """The second outlet is strong evidence; the tenth adds little."""
    first_step = _score(independent_sources=2) - _score(independent_sources=1)
    later_step = _score(independent_sources=8) - _score(independent_sources=7)
    assert first_step > later_step


def test_single_source_items_are_not_penalised() -> None:
    """Most releases are legitimately announced once; the factor lifts
    corroborated events rather than demoting everything else."""
    factors = score_item(
        quality_score=70.0,
        source_tier="primary",
        content_type="model_release",
        age_hours=1.0,
        body_chars=4000,
        independent_sources=1,
    )
    assert factors.corroboration == 0.0


def test_media_coverage_can_now_beat_a_routine_release() -> None:
    """A four-outlet news event on a secondary source against a primary-tier
    release note — the exact comparison the shortlist used to get wrong."""
    news = _score(
        source_tier="secondary", content_type="security", independent_sources=4, quality_score=75
    )
    routine = _score(
        source_tier="primary",
        content_type="product_release",
        independent_sources=1,
        quality_score=75,
    )
    assert news > routine


def test_score_stays_within_range() -> None:
    high = _score(quality_score=100, source_tier="primary", age_hours=0, body_chars=100000)
    low = _score(quality_score=0, source_tier="community", age_hours=1000, body_chars=0)
    assert 0.0 <= low <= high <= 100.0


def test_freshness_never_goes_negative() -> None:
    """A very old item is worth zero freshness, not a negative contribution."""
    assert (
        score_item(
            quality_score=50.0,
            source_tier="primary",
            content_type="research",
            age_hours=10_000.0,
            body_chars=1000,
        ).freshness
        == 0.0
    )


def test_top_reasons_names_three_factors() -> None:
    factors = score_item(
        quality_score=90.0,
        source_tier="primary",
        content_type="model_release",
        age_hours=1.0,
        body_chars=5000,
    )
    reasons = factors.top_reasons()
    assert reasons
    assert len(reasons.split("、")) == 3


def test_quota_constants_prevent_single_source_domination() -> None:
    """53 of the sources are GitHub release feeds; one must not fill a day."""
    assert MAX_PER_SOURCE_PER_DAY < DAILY_QUOTA


def test_reselecting_preserves_an_llm_written_reason() -> None:
    """Re-ranking must not overwrite analysis with the factor list.

    The upsert used to set `reason = EXCLUDED.reason` unconditionally while
    leaving `reason_version` untouched. On the first scheduled pipeline pass that
    replaced 90 of 97 LLM reasons with "一手/权威来源、属于关键变更类型…" — and
    since the version still said recommend-v2, the backfill treated every row as
    done and never wrote them back.
    """
    import re

    from ahr.processing import selection

    source = inspect.getsource(selection.select_for_days)
    upsert = source[source.index("ON CONFLICT (content_item_id") :]

    # The unconditional assignment must not be there...
    assert not re.search(r"^\s*reason = EXCLUDED\.reason,\s*$", upsert, re.MULTILINE)
    # ...and the guard must reference the version column.
    assert "selection_record.reason_version IS NOT NULL" in upsert


def test_selection_does_not_clear_the_reason_version() -> None:
    """Clearing it would make every pass re-pay for reasons that already exist."""
    from ahr.processing import selection

    source = inspect.getsource(selection.select_for_days)
    assert "reason_version = NULL" not in source


def test_every_content_type_has_a_weight() -> None:
    """A missing weight would silently score an entire category as the default."""
    for content_type in get_args(ContentType):
        assert content_type in CONTENT_TYPE_WEIGHT, content_type

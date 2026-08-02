"""Topic normalisation and editorial selection tests (M2)."""

from __future__ import annotations

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


def test_known_slugs_includes_parents_and_children() -> None:
    taxonomy = {"models": ["llm", "multimodal"], "business": ["funding"]}
    assert known_slugs(taxonomy) == {"models", "llm", "multimodal", "business", "funding"}


# --- selection scoring ---------------------------------------------------


def _score(**overrides: object) -> float:
    base: dict[str, object] = {
        "quality_score": 70.0,
        "source_tier": "primary",
        "content_type": "model_release",
        "age_hours": 1.0,
        "body_chars": 4000,
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


def test_every_content_type_has_a_weight() -> None:
    """A missing weight would silently score an entire category as the default."""
    for content_type in get_args(ContentType):
        assert content_type in CONTENT_TYPE_WEIGHT, content_type

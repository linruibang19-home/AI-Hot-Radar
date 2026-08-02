"""Heat scoring tests."""

from __future__ import annotations

from ahr.processing.heat import freshness_decay, score


def heat(**overrides: object) -> float:
    base: dict[str, object] = {
        "age_hours": 2.0,
        "source_tier": "primary",
        "content_type": "model_release",
        "quality_score": 80.0,
        "independent_source_count": 1,
    }
    base.update(overrides)
    return score(**base).total()  # type: ignore[arg-type]


def test_fresher_content_outranks_older() -> None:
    assert heat(age_hours=1) > heat(age_hours=48)


def test_decay_halves_at_the_half_life() -> None:
    from ahr.processing.heat import HALF_LIFE_HOURS

    assert freshness_decay(HALF_LIFE_HOURS) == 0.5
    assert freshness_decay(0) == 1.0


def test_model_release_outranks_a_fresher_paper() -> None:
    """Regression: additive weighting let a routine preprint top the list."""
    release = heat(content_type="model_release", age_hours=12)
    paper = heat(content_type="research", age_hours=1)
    assert release > paper


def test_unenriched_content_does_not_lead() -> None:
    """Items with no known type must not outrank classified releases."""
    assert heat(content_type=None, quality_score=None) < heat(content_type="model_release")


def test_broader_coverage_raises_heat_but_saturates() -> None:
    one, two, ten = (
        heat(independent_source_count=1),
        heat(independent_source_count=2),
        heat(independent_source_count=10),
    )
    assert one < two < ten
    # The second outlet should matter more than the tenth.
    assert (two - one) > (ten - two) / 8


def test_primary_source_outranks_community() -> None:
    assert heat(source_tier="primary") > heat(source_tier="community")


def test_opinion_ranks_below_releases() -> None:
    assert heat(content_type="opinion") < heat(content_type="product_release")


def test_heat_is_never_negative() -> None:
    assert heat(age_hours=10_000, quality_score=0, source_tier="community") >= 0

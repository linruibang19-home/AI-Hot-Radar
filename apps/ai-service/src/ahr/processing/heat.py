"""Heat scoring for the hot list.

AHR-PRD-100 §4 keeps this deliberately separate from `quality_score`:

    quality_score  judges one article, 0-100, stable once computed
    hot_score      measures how much attention an event is drawing right now,
                   decays with time, and is not bounded to 100

The suggested shape is:

    hot_score = freshness_decay * (primary_source_bonus
                                   + log1p(independent_source_count) * 20
                                   + cross_region_bonus + engagement_signal)

Independent-source counting properly requires Story clustering (M3). Until then
this approximates it by grouping near-duplicates, which is the same signal at a
smaller scale: two outlets publishing the same release is evidence of attention.
Engagement signals need social data that MVP does not collect, so that term is
zero rather than invented.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

HEAT_ALGORITHM_VERSION = "heat-v1"

# Half-life in hours. AI news goes stale fast; a day-old release should already
# rank below something published this morning.
HALF_LIFE_HOURS = 18.0

PRIMARY_SOURCE_BONUS = 30.0
SECONDARY_SOURCE_BONUS = 12.0
EXPERT_SOURCE_BONUS = 18.0

# Editorial weight per type, applied as a multiplier rather than an additive
# bonus. Additively, a routine paper published two hours ago outranked a major
# model release from the same morning, because freshness swamped everything
# else. As a multiplier the type sets the ceiling and freshness orders within it.
CONTENT_TYPE_WEIGHT = {
    "model_release": 1.0,
    "product_release": 0.9,
    "api_update": 0.8,
    "security": 0.8,
    "open_source": 0.6,
    "business": 0.55,
    "policy": 0.5,
    # arXiv publishes dozens of papers a day. A single uncorroborated preprint
    # is not "hot" in the sense this list means, however good it is.
    "research": 0.45,
    "tutorial": 0.3,
    "opinion": 0.25,
}

# Content that has not been enriched has no known type. It must not lead the
# list by default, which is what an average weight would let it do.
UNKNOWN_TYPE_WEIGHT = 0.35


@dataclass
class HeatFactors:
    freshness_decay: float
    source_bonus: float
    independent_sources: float
    type_weight: float
    quality_bonus: float

    def total(self) -> float:
        base = self.source_bonus + self.independent_sources + self.quality_bonus
        return round(self.freshness_decay * self.type_weight * base, 3)


def freshness_decay(age_hours: float) -> float:
    """Exponential decay with a fixed half-life.

    Exponential rather than linear: linear decay would let a three-day-old item
    keep a third of its heat, which is not how attention to a release behaves.
    """
    if age_hours <= 0:
        return 1.0
    return math.pow(0.5, age_hours / HALF_LIFE_HOURS)


def score(
    *,
    age_hours: float,
    source_tier: str,
    content_type: str | None,
    quality_score: float | None,
    independent_source_count: int,
) -> HeatFactors:
    tier_bonus = {
        "primary": PRIMARY_SOURCE_BONUS,
        "expert": EXPERT_SOURCE_BONUS,
        "secondary": SECONDARY_SOURCE_BONUS,
    }.get(source_tier, 6.0)

    return HeatFactors(
        freshness_decay=freshness_decay(age_hours),
        source_bonus=tier_bonus,
        # log1p so the tenth outlet adds far less than the second: breadth of
        # coverage matters, but it saturates.
        independent_sources=math.log1p(max(independent_source_count - 1, 0)) * 20.0,
        type_weight=(
            CONTENT_TYPE_WEIGHT.get(content_type, UNKNOWN_TYPE_WEIGHT)
            if content_type
            else UNKNOWN_TYPE_WEIGHT
        ),
        quality_bonus=(quality_score or 50.0) * 0.15,
    )


def rescore(connection: Any, *, days: int = 7) -> dict[str, Any]:
    """Recompute heat for recent content."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.id, s.source_tier, ci.content_type, ci.quality_score,
                   EXTRACT(EPOCH FROM (now() - COALESCE(ci.published_at, ci.observed_at)))/3600.0,
                   1 + (SELECT count(*) FROM content_item d
                         WHERE d.duplicate_of_id = ci.id)
              FROM content_item ci
              JOIN source s ON s.id = ci.source_id
             WHERE ci.duplicate_of_id IS NULL
               AND COALESCE(ci.published_at, ci.observed_at) > now() - (%s || ' days')::interval
            """,
            (days,),
        )
        rows = cursor.fetchall()

        updates = []
        for item_id, tier, content_type, quality, age_hours, source_count in rows:
            factors = score(
                age_hours=float(age_hours or 0),
                source_tier=tier,
                content_type=content_type,
                quality_score=float(quality) if quality is not None else None,
                independent_source_count=int(source_count or 1),
            )
            updates.append((factors.total(), int(source_count or 1), item_id))

        cursor.executemany(
            """
            UPDATE content_item
               SET hot_score = %s, independent_source_count = %s, hot_scored_at = now()
             WHERE id = %s
            """,
            updates,
        )

    connection.commit()
    top = max((u[0] for u in updates), default=0.0)
    return {"scored": len(updates), "max_heat": top, "algorithm": HEAT_ALGORITHM_VERSION}

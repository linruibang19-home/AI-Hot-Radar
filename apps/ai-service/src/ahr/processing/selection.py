"""Editorial selection for the curated homepage.

AHR-FEAT-101 asks for "AI 自动挑选的高价值内容" with a stated reason, not simply
the newest rows. AHR-PRD-100 §4 also requires the score breakdown to be stored
so the UI can explain the top contributing factors.

Selection is deliberately per-day: the homepage groups by date, so each day gets
its own ranked shortlist rather than one global ranking that would starve quiet
days entirely.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

ALGORITHM_VERSION = "select-v1"

# How many items may be selected per day. Small enough to stay curated, large
# enough that a busy release day is not truncated to a single vendor.
DAILY_QUOTA = 12

# One source should not occupy the whole day: 53 of the sources are GitHub
# release feeds and would otherwise dominate every date group.
MAX_PER_SOURCE_PER_DAY = 3

TIER_WEIGHT = {"primary": 1.0, "expert": 0.85, "secondary": 0.7, "community": 0.5}

# Types that represent a concrete, verifiable change rank above commentary.
CONTENT_TYPE_WEIGHT = {
    "model_release": 1.0,
    "product_release": 0.95,
    "api_update": 0.9,
    "research": 0.8,
    "open_source": 0.75,
    "security": 0.9,
    "policy": 0.7,
    "business": 0.65,
    "tutorial": 0.6,
    "opinion": 0.45,
}


@dataclass
class SelectionFactors:
    quality: float = 0.0
    source_tier: float = 0.0
    content_type: float = 0.0
    freshness: float = 0.0
    body_depth: float = 0.0

    def total(self) -> float:
        return round(
            0.40 * self.quality
            + 0.20 * self.source_tier
            + 0.20 * self.content_type
            + 0.10 * self.freshness
            + 0.10 * self.body_depth,
            2,
        )

    def top_reasons(self) -> str:
        """The three largest contributors, for the UI's "为什么入选" line."""
        labels = {
            "quality": "内容质量高",
            "source_tier": "一手/权威来源",
            "content_type": "属于关键变更类型",
            "freshness": "发布时间新",
            "body_depth": "正文信息量充足",
        }
        ranked = sorted(asdict(self).items(), key=lambda kv: kv[1], reverse=True)
        return "、".join(labels[name] for name, value in ranked[:3] if value > 0)


def score_item(
    *,
    quality_score: float | None,
    source_tier: str,
    content_type: str | None,
    age_hours: float,
    body_chars: int,
) -> SelectionFactors:
    """Score one candidate on a 0-100 scale per factor."""
    factors = SelectionFactors()

    # Unenriched content still competes, just from a neutral baseline, so the
    # homepage does not go empty when the model is unavailable.
    factors.quality = quality_score if quality_score is not None else 50.0

    factors.source_tier = TIER_WEIGHT.get(source_tier, 0.5) * 100
    factors.content_type = CONTENT_TYPE_WEIGHT.get(content_type or "", 0.6) * 100

    # Linear decay over three days; older content can still be selected on its
    # own date, it simply cannot outrank fresh items on that day.
    factors.freshness = max(0.0, 100.0 - (age_hours / 72.0) * 100.0)

    # Rewards substance up to ~4000 characters, then flattens so a long paper
    # does not automatically outrank a short but important release note.
    factors.body_depth = min(body_chars / 4000.0, 1.0) * 100

    return factors


@dataclass
class Candidate:
    item_id: uuid.UUID
    source_id: str
    day: date
    factors: SelectionFactors
    score: float


def select_for_days(connection: Any, *, days: int = 7) -> dict[str, int]:
    """Rank recent content and record the per-day shortlist."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.id, ci.source_id, s.source_tier, ci.content_type,
                   ci.quality_score,
                   COALESCE(ci.published_at, ci.observed_at) AS stamp,
                   EXTRACT(EPOCH FROM (now() - COALESCE(ci.published_at, ci.observed_at))) / 3600.0,
                   COALESCE(length(cr.body_text), 0)
              FROM content_item ci
              JOIN source s ON s.id = ci.source_id
              LEFT JOIN content_revision cr ON cr.id = ci.current_revision_id
             WHERE ci.duplicate_of_id IS NULL
               AND COALESCE(ci.published_at, ci.observed_at) > now() - (%s || ' days')::interval
               AND COALESCE(ci.published_at, ci.observed_at) <= now()
            """,
            (days,),
        )
        rows = cursor.fetchall()

    candidates: list[Candidate] = []
    for row in rows:
        item_id, source_id, tier, content_type, quality, stamp, age_hours, body_chars = row
        factors = score_item(
            quality_score=float(quality) if quality is not None else None,
            source_tier=tier,
            content_type=content_type,
            age_hours=float(age_hours or 0),
            body_chars=int(body_chars or 0),
        )
        candidates.append(
            Candidate(
                item_id=uuid.UUID(str(item_id)),
                source_id=source_id,
                day=stamp.date(),
                factors=factors,
                score=factors.total(),
            )
        )

    by_day: dict[date, list[Candidate]] = {}
    for candidate in candidates:
        by_day.setdefault(candidate.day, []).append(candidate)

    written = 0
    for day, group in by_day.items():
        group.sort(key=lambda c: c.score, reverse=True)

        per_source: dict[str, int] = {}
        chosen: list[Candidate] = []
        for candidate in group:
            if len(chosen) >= DAILY_QUOTA:
                break
            used = per_source.get(candidate.source_id, 0)
            if used >= MAX_PER_SOURCE_PER_DAY:
                continue
            per_source[candidate.source_id] = used + 1
            chosen.append(candidate)

        with connection.cursor() as cursor:
            # Withdraw the previous automatic shortlist for this day so a rerun
            # replaces it. Editor choices are left untouched.
            cursor.execute(
                """
                UPDATE selection_record SET withdrawn_at = now()
                 WHERE selected_for_date = %s AND selected_by = 'auto'
                   AND withdrawn_at IS NULL
                """,
                (day,),
            )
            for candidate in chosen:
                cursor.execute(
                    """
                    INSERT INTO selection_record (
                        id, content_item_id, selected_for_date, score, reason,
                        factors, algorithm_version, selected_by, withdrawn_at
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, 'auto', NULL)
                    ON CONFLICT (content_item_id, selected_for_date) DO UPDATE SET
                        score = EXCLUDED.score,
                        reason = EXCLUDED.reason,
                        factors = EXCLUDED.factors,
                        algorithm_version = EXCLUDED.algorithm_version,
                        withdrawn_at = NULL
                    """,
                    (
                        uuid.uuid4(),
                        candidate.item_id,
                        day,
                        candidate.score,
                        candidate.factors.top_reasons(),
                        json.dumps(asdict(candidate.factors)),
                        ALGORITHM_VERSION,
                    ),
                )
                written += 1

    connection.commit()
    return {"days": len(by_day), "candidates": len(candidates), "selected": written}

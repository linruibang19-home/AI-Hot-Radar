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
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

# v3 keeps the scoring formula and adds portfolio constraints.  The version is
# recorded per selection so a shortlist produced before source-family/content-
# type diversity can be distinguished from the current one.
ALGORITHM_VERSION = "select-v3"

# How many items may be selected per day. Small enough to stay curated, large
# enough that a busy release day is not truncated to a single vendor.
DAILY_QUOTA = 12

# One source should not occupy the whole day: 53 of the sources are GitHub
# release feeds and would otherwise dominate every date group.
MAX_PER_SOURCE_PER_DAY = 3

# A configured source is not always an independent editorial voice.  arXiv has
# seven subject feeds in the registry; counting each subject as a separate
# source let one daily batch occupy all twelve homepage slots.  Keep papers in
# the shortlist, but treat the feeds as one publisher family.
MAX_PER_SOURCE_FAMILY_PER_DAY = 3

# Research is important, but the curated homepage is a cross-section of the AI
# industry rather than a paper-only feed.  Four of twelve leaves room for model,
# product, security, policy and business changes while still surfacing the top
# papers.  The uncurated content library remains available for readers who want
# every research item; this cap applies only to the twelve-item shortlist.
MAX_PER_CONTENT_TYPE_PER_DAY = {"research": 4}

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
    corroboration: float = 0.0

    def total(self) -> float:
        return round(
            0.34 * self.quality
            + 0.17 * self.source_tier
            + 0.17 * self.content_type
            + 0.09 * self.freshness
            + 0.08 * self.body_depth
            + 0.15 * self.corroboration,
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
            "corroboration": "多家独立信源报道",
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
    independent_sources: int = 1,
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

    # How many independent outlets covered the same event (M3).
    #
    # Without this term the shortlist could not see corroboration at all, and it
    # showed: the two events that four and three independent outlets each
    # reported — Anthropic's Claude security incident and Google pulling its
    # satellite-deepfake tool — were selected zero times, while 87 single-source
    # release notes were. Media coverage sits in the secondary/expert tiers and
    # lost every comparison to a primary-tier GitHub release.
    #
    # Saturating rather than linear: the second outlet is strong evidence an
    # event matters, the fifth adds little. A single-source item scores 0 here
    # rather than being penalised — most releases are legitimately announced
    # once, so this lifts corroborated events instead of demoting the rest.
    factors.corroboration = (
        min(math.log1p(max(independent_sources - 1, 0)) / math.log(4), 1.0) * 100
    )

    return factors


@dataclass
class Candidate:
    item_id: uuid.UUID
    source_id: str
    source_family: str
    content_type: str | None
    day: date
    factors: SelectionFactors
    score: float


def source_family(source_id: str, profile: str) -> str:
    """Return the editorial publisher family used by diversity constraints."""
    if profile == "arxiv_feed_paper" or source_id.startswith("arxiv-"):
        return "arxiv"
    return source_id


def choose_daily(group: list[Candidate]) -> list[Candidate]:
    """Choose one scored daily portfolio with publisher and type diversity."""
    group.sort(key=lambda candidate: candidate.score, reverse=True)
    per_source: dict[str, int] = {}
    per_family: dict[str, int] = {}
    per_content_type: dict[str, int] = {}
    chosen: list[Candidate] = []
    for candidate in group:
        if len(chosen) >= DAILY_QUOTA:
            break
        used = per_source.get(candidate.source_id, 0)
        if used >= MAX_PER_SOURCE_PER_DAY:
            continue
        family_used = per_family.get(candidate.source_family, 0)
        if family_used >= MAX_PER_SOURCE_FAMILY_PER_DAY:
            continue
        content_type = candidate.content_type or "unknown"
        type_used = per_content_type.get(content_type, 0)
        type_limit = MAX_PER_CONTENT_TYPE_PER_DAY.get(content_type, DAILY_QUOTA)
        if type_used >= type_limit:
            continue
        per_source[candidate.source_id] = used + 1
        per_family[candidate.source_family] = family_used + 1
        per_content_type[content_type] = type_used + 1
        chosen.append(candidate)
    return chosen


def select_for_days(connection: Any, *, days: int = 7) -> dict[str, int]:
    """Rank recent content and record the per-day shortlist."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.id, ci.source_id, s.profile, s.source_tier, ci.content_type,
                   ci.quality_score,
                   COALESCE(ci.published_at, ci.observed_at)
                       AT TIME ZONE 'Asia/Shanghai' AS editorial_stamp,
                   EXTRACT(EPOCH FROM (now() - COALESCE(ci.published_at, ci.observed_at))) / 3600.0,
                   COALESCE(length(cr.body_text), 0),
                   COALESCE(st.independent_source_count, 1)
              FROM content_item ci
              JOIN source s ON s.id = ci.source_id
              LEFT JOIN content_revision cr ON cr.id = ci.current_revision_id
              LEFT JOIN story st ON st.id = ci.story_id
             WHERE ci.duplicate_of_id IS NULL
               AND COALESCE(ci.published_at, ci.observed_at) > now() - (%s || ' days')::interval
               AND COALESCE(ci.published_at, ci.observed_at) <= now()
            """,
            (days,),
        )
        rows = cursor.fetchall()

    candidates: list[Candidate] = []
    for row in rows:
        (
            item_id,
            source_id,
            profile,
            tier,
            content_type,
            quality,
            stamp,
            age_hours,
            body_chars,
            independent_sources,
        ) = row
        factors = score_item(
            quality_score=float(quality) if quality is not None else None,
            source_tier=tier,
            content_type=content_type,
            age_hours=float(age_hours or 0),
            body_chars=int(body_chars or 0),
            independent_sources=int(independent_sources or 1),
        )
        candidates.append(
            Candidate(
                item_id=uuid.UUID(str(item_id)),
                source_id=source_id,
                source_family=source_family(source_id, profile),
                content_type=content_type,
                # The SQL expression already converted the timestamp to the
                # product's editorial timezone.  A 00:30 CST release therefore
                # cannot be selected under the previous UTC day.
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
        chosen = choose_daily(group)

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
                        factors = EXCLUDED.factors,
                        algorithm_version = EXCLUDED.algorithm_version,
                        withdrawn_at = NULL,
                        -- Keep an LLM-written reason. Re-ranking changes the
                        -- score, not what the article says, so overwriting it
                        -- with the factor list would replace real analysis with
                        -- the boilerplate this pipeline exists to avoid — and
                        -- because reason_version stayed set, the backfill then
                        -- considered the row done and never restored it. That
                        -- silently reverted 90 of 97 cards to the templated
                        -- text on the first scheduled pass.
                        reason = CASE
                            WHEN selection_record.reason_version IS NOT NULL
                            THEN selection_record.reason
                            ELSE EXCLUDED.reason
                        END
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

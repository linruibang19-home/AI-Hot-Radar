"""Query planning and fusion.

The time tests all pin `asked_at` to a fixed instant. A planner test that read
the wall clock would pass today and fail on a Monday, which is the least useful
kind of test there is.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ahr.rag.fusion import (
    BOOST_IN_TIME_WINDOW,
    BOOST_PRIMARY_SOURCE,
    PENALTY_OPINION_FOR_FACT,
    apply_boosts,
    reciprocal_rank_fusion,
)
from ahr.rag.planner import (
    DISPLAY_TIMEZONE,
    RECENT_DAYS,
    UNSPECIFIED_DAYS,
    classify,
    plan,
    resolve_time_range,
)
from ahr.rag.retrieval import ChunkHit

# Monday 2026-08-03, 12:00 Beijing time.
ASKED_AT = datetime(2026, 8, 3, 12, 0, tzinfo=DISPLAY_TIMEZONE)


def _hit(chunk_id: str, item_id: str | None = None) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        content_item_id=item_id or chunk_id,
        score=0.5,
        title="",
        source_name="",
    )


# --------------------------------------------------------------------------
# time resolution
# --------------------------------------------------------------------------


def test_recent_without_a_span_defaults_to_seven_days() -> None:
    window = resolve_time_range("Cloudflare 最近有什么新动作？", ASKED_AT)
    assert window is not None
    assert window.end - window.start == timedelta(days=RECENT_DAYS)
    # Not explicit, because the reader never said seven days — the answer has to
    # tell them that is what was searched (AHR-RAG-400 §3).
    assert window.explicit is False


def test_today_is_bounded_by_the_display_timezone_not_utc() -> None:
    # Asked at noon Beijing time, which is 04:00 UTC. A UTC-based day boundary
    # would start the window eight hours early and pull in yesterday evening —
    # the same defect that once made the whole site render times a day off.
    window = resolve_time_range("今天有什么 AI 新闻？", ASKED_AT)
    assert window is not None
    local_start = window.start.astimezone(DISPLAY_TIMEZONE)
    assert (local_start.year, local_start.month, local_start.day) == (2026, 8, 3)
    assert (local_start.hour, local_start.minute) == (0, 0)
    assert window.end - window.start == timedelta(days=1)


def test_yesterday_is_the_previous_local_day() -> None:
    window = resolve_time_range("昨天发布了什么模型？", ASKED_AT)
    assert window is not None
    local_start = window.start.astimezone(DISPLAY_TIMEZONE)
    assert local_start.day == 2
    assert window.end - window.start == timedelta(days=1)


def test_this_week_starts_on_monday() -> None:
    window = resolve_time_range("本周有哪些监管消息？", ASKED_AT)
    assert window is not None
    local_start = window.start.astimezone(DISPLAY_TIMEZONE)
    # 2026-08-03 is itself a Monday, so the week starts today.
    assert local_start.weekday() == 0
    assert local_start.day == 3
    assert window.explicit is True


def test_last_week_is_matched_before_this_week() -> None:
    # "上周" contains no substring that "本周" matches, but the ordering matters
    # for phrases that overlap; this pins the intended resolution.
    window = resolve_time_range("上周发生了什么？", ASKED_AT)
    assert window is not None
    local_start = window.start.astimezone(DISPLAY_TIMEZONE)
    assert local_start.day == 27
    assert local_start.month == 7


def test_last_month_spans_the_previous_calendar_month() -> None:
    window = resolve_time_range("上个月有哪些大模型发布？", ASKED_AT)
    assert window is not None
    start = window.start.astimezone(DISPLAY_TIMEZONE)
    end = window.end.astimezone(DISPLAY_TIMEZONE)
    assert (start.year, start.month, start.day) == (2026, 7, 1)
    assert (end.year, end.month, end.day) == (2026, 8, 1)


def test_an_explicit_day_count_wins_over_the_default() -> None:
    window = resolve_time_range("最近 3 天 llama.cpp 发布了什么？", ASKED_AT)
    assert window is not None
    assert window.end - window.start == timedelta(days=3)
    assert window.explicit is True


def test_an_explicit_week_count_is_understood() -> None:
    window = resolve_time_range("最近 2 周有哪些开源模型？", ASKED_AT)
    assert window is not None
    assert window.end - window.start == timedelta(weeks=2)


def test_a_question_without_time_sense_gets_no_window() -> None:
    # Restricting "how does this architecture work" to last week would exclude
    # the document that explains it.
    assert resolve_time_range("NEO-Unify 架构是怎么工作的？", ASKED_AT) is None


def test_planner_requires_an_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        plan("最近有什么新闻", asked_at=datetime(2026, 8, 3, 12, 0))


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Anthropic 那起事故是怎么一步步曝光的？", "timeline"),
        ("Kimi K3 和 GPT-5.6 Sol 相比怎么样？", "comparison"),
        ("Cloudflare 最近有什么新动作？", "recent_updates"),
        ("Qwen3.8-Max 有多少参数？", "fact_check"),
        ("为什么说代理需要一台计算机？", "explainer"),
    ],
)
def test_classification(question: str, expected: str) -> None:
    assert classify(question) == expected


def test_recent_updates_without_a_time_word_falls_back_to_thirty_days() -> None:
    result = plan("有哪些新的开源多模态模型？", asked_at=ASKED_AT)
    assert result.query_type == "recent_updates"
    assert result.time_range is not None
    span = result.time_range.end - result.time_range.start
    assert abs(span - timedelta(days=UNSPECIFIED_DAYS)) < timedelta(seconds=1)
    assert result.notes  # the fallback must be stated, not applied silently


def test_plan_is_serialisable_for_the_rag_query_row() -> None:
    payload = plan("最近有什么新闻", asked_at=ASKED_AT).as_dict()
    assert payload["query_type"]
    assert payload["time_range"]["timezone"] == str(ZoneInfo("Asia/Shanghai"))


# --------------------------------------------------------------------------
# fusion
# --------------------------------------------------------------------------


def test_rrf_rewards_a_chunk_found_by_both_channels() -> None:
    """The property the round-robin merge lacked.

    B2 measured interleaving as worse than dense alone on every metric because
    it could not express agreement. Here `shared` is second in both channels and
    must outrank a chunk that is first in only one.
    """
    dense = [_hit("solo"), _hit("shared")]
    sparse = [_hit("other"), _hit("shared")]
    fused = reciprocal_rank_fusion(
        {"dense": dense, "sparse": sparse}, weights={"dense": 1.0, "sparse": 1.0}
    )
    assert fused[0].chunk_id == "shared"
    assert set(fused[0].channels) == {"dense", "sparse"}


def test_rrf_weights_the_weaker_channel_down() -> None:
    # Sparse-only Recall@20 measured 0.4662 against dense's 0.8876, so an equal
    # split would repeat the interleave regression.
    fused = reciprocal_rank_fusion(
        {"dense": [_hit("d")], "sparse": [_hit("s")]},
        weights={"dense": 1.0, "sparse": 0.6},
    )
    assert [hit.chunk_id for hit in fused] == ["d", "s"]


def test_rrf_ordering_is_deterministic_for_ties() -> None:
    # Two evaluation runs must not differ because of dictionary iteration order.
    channels = {"dense": [_hit("b"), _hit("a")], "sparse": []}
    first = [hit.chunk_id for hit in reciprocal_rank_fusion(channels)]
    second = [hit.chunk_id for hit in reciprocal_rank_fusion(channels)]
    assert first == second


def test_rrf_handles_an_empty_channel() -> None:
    fused = reciprocal_rank_fusion({"dense": [_hit("d")], "sparse": []})
    assert [hit.chunk_id for hit in fused] == ["d"]


def test_boosts_are_applied_once_each() -> None:
    published = ASKED_AT - timedelta(days=1)
    fused = reciprocal_rank_fusion({"dense": [_hit("top", "other"), _hit("c", "item")]})

    boosted = apply_boosts(
        fused,
        {
            "item": {
                "source_tier": "primary",
                "content_type": "model_release",
                "published_at": published,
            }
        },
        query_type="recent_updates",
        window=(ASKED_AT - timedelta(days=7), ASKED_AT),
    )
    scored = {hit.chunk_id: hit for hit in boosted}
    # Normalised to [0, 1]: last place becomes 0, then the two boosts land.
    assert scored["c"].score == pytest.approx(BOOST_PRIMARY_SOURCE + BOOST_IN_TIME_WINDOW)
    assert set(scored["c"].boosts) == {"primary_source", "in_time_window"}


def test_boosts_are_scaled_against_the_normalised_score_not_the_raw_rrf() -> None:
    """Regression for the first B3 run.

    A raw RRF score is about 1/(60+rank) ≈ 0.016, while §6 specifies boosts of
    ±0.05 to ±0.15 — up to ten times the entire spread. Applied to the raw score
    they stopped being adjustments and became the ranking, and `fact_check`
    Recall@10 fell from 0.9556 to 0.2556. After normalisation a single boost
    must not be able to lift the bottom of the list over the top.
    """
    hits = [_hit(f"c{i}", f"item{i}") for i in range(10)]
    fused = reciprocal_rank_fusion({"dense": hits})
    boosted = apply_boosts(
        fused,
        {"item9": {"source_tier": "primary", "content_type": "x", "published_at": None}},
        query_type="explainer",
        window=None,
    )
    assert boosted[0].chunk_id == "c0"
    assert boosted[0].score == pytest.approx(1.0)


def test_opinion_is_penalised_only_for_fact_check() -> None:
    meta = {"item": {"source_tier": "secondary", "content_type": "opinion", "published_at": None}}

    def score_for(query_type: str) -> float:
        fused = reciprocal_rank_fusion({"dense": [_hit("c", "item"), _hit("tail", "tail")]})
        boosted = apply_boosts(fused, meta, query_type=query_type, window=None)
        return next(hit.score for hit in boosted if hit.chunk_id == "c")

    assert score_for("fact_check") == pytest.approx(1.0 + PENALTY_OPINION_FOR_FACT)
    # An opinion piece answering an opinion question is exactly the right
    # evidence and must not be pushed down.
    assert score_for("comparison") == pytest.approx(1.0)


def test_boosts_skip_items_without_metadata() -> None:
    fused = reciprocal_rank_fusion({"dense": [_hit("c", "unknown"), _hit("d", "other")]})
    boosted = apply_boosts(fused, {}, query_type="fact_check", window=None)
    # Normalisation still happens; no boost is added and the order is unchanged.
    assert [hit.chunk_id for hit in boosted] == ["c", "d"]
    assert boosted[0].score == pytest.approx(1.0)
    assert boosted[1].score == pytest.approx(0.0)

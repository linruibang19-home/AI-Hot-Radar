"""Event clustering tests (M3, AHR-DATA-300 §8).

The cases are drawn from real rows in the corpus. The hardest one is the
DeepSeek group: three outlets covering the V4-Flash release must merge, while
"DeepSeek-V3" and the llama.cpp/vLLM releases that merely mention DeepSeek must
stay out. Purity is what AHR-KPI-003 measures, so the split cases matter more
than the merge cases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ahr.processing.story import (
    MERGE_THRESHOLD,
    SUGGEST_THRESHOLD,
    Candidate,
    cluster,
    containment,
    extract_versions,
    independent_sources,
    jaccard,
    primary_rank,
    score_pair,
    slugify,
    time_proximity,
    tokenize,
    version_conflict,
)

BASE = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def make(
    title: str,
    *,
    source_id: str = "src",
    organization: str | None = "Org",
    tier: str = "primary",
    content_type: str | None = "model_release",
    hours: float = 0.0,
    entities: set[str] | None = None,
    topics: set[str] | None = None,
    quality: float | None = 75.0,
) -> Candidate:
    import uuid as _uuid

    return Candidate(
        item_id=_uuid.uuid4(),
        title=title,
        source_id=source_id,
        organization=organization,
        source_tier=tier,
        content_type=content_type,
        published_at=BASE + timedelta(hours=hours),
        quality_score=quality,
        entity_ids=frozenset(entities or {"deepseek"}),
        topic_ids=frozenset(topics or {"llm"}),
        tokens=tokenize(title),
        versions=extract_versions(title),
    )


# --- tokenisation ---------------------------------------------------------


def test_cjk_is_tokenised_as_bigrams() -> None:
    """Single characters are too common to discriminate; whole strings never match."""
    tokens = tokenize("模型发布公告")
    assert "公告" in tokens
    assert all(len(token) <= 2 for token in tokens if token.isalpha() is False or True)


def test_stopwords_do_not_make_every_release_similar() -> None:
    left = tokenize("Mistral Small 4 发布")
    right = tokenize("Cohere Command A+ 发布")
    assert jaccard(left, right) < 0.2


def test_width_and_case_are_folded() -> None:
    assert tokenize("ＧＰＴ") == tokenize("gpt")


# --- version extraction ---------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("DeepSeek-V4-Flash 正式版 API 上线公测", {"4"}),
        ("vLLM v0.26.0 发布", {"0.26.0"}),
        ("llama.cpp b10217 发布", {"b10217"}),
        ("MiniCPM-V 4.6 下采样支持", {"4.6"}),
        ("没有版本号的标题", set()),
    ],
)
def test_extract_versions(title: str, expected: set[str]) -> None:
    assert extract_versions(title) == expected


# --- hard rules -----------------------------------------------------------


def test_different_versions_of_one_product_never_merge() -> None:
    """docs/spec/03 §8: 不同模型版本不得仅因公司相同合并.

    This is a factual-correctness rule, not a ranking preference: V3 and V4 are
    different releases however similar their coverage reads.
    """
    v3 = make("DeepSeek-V3 发布：高效 MoE 模型，性能比肩闭源")
    v4 = make("DeepSeek V4 发布：高效 MoE 模型，性能比肩闭源")

    assert version_conflict(v3, v4)
    assert score_pair(v3, v4).veto == "version_conflict"


def test_version_rule_does_not_block_when_only_one_side_is_versioned() -> None:
    """Coverage often omits the version; requiring it on both sides would split
    the announcement away from the reporting about it."""
    announcement = make("DeepSeek V4-Flash 发布")
    coverage = make("DeepSeek 新模型性能跃升引发热议", content_type="opinion")
    assert not version_conflict(announcement, coverage)


def test_two_releases_from_the_same_feed_stay_separate() -> None:
    """A release feed publishing twice is publishing twice, not covering once."""
    first = make("llama.cpp b10217 发布", source_id="llama", hours=0)
    second = make("llama.cpp b10218 发布", source_id="llama", hours=1)
    assert score_pair(first, second).veto is not None


@pytest.mark.parametrize(
    ("left_title", "right_title"),
    [
        # Four separate incidents on one status page, all phrased alike.
        ("ChatGPT 对话服务错误率升高已恢复", "ChatGPT 图像生成服务故障已恢复"),
        # Six posts whose titles all extracted as the link text.
        ("Read More", "Read More"),
    ],
)
def test_same_source_never_merges_however_similar(left_title: str, right_title: str) -> None:
    """Both cases are real: they were the top-scoring pairs in the corpus.

    A Story exists to count independent corroboration, so two items from one
    publisher cannot improve the ranking — but they can and did produce wrong
    groupings out of one outlet's house phrasing.
    """
    left = make(left_title, source_id="one-feed", content_type="security")
    right = make(right_title, source_id="one-feed", content_type="security", hours=3)
    assert score_pair(left, right).veto == "same_source"


def test_containment_survives_lopsided_entity_lists() -> None:
    """The measure that made real clustering work at all.

    A changelog entry naming 5 entities and a write-up naming 10 that agree on
    the 2 the event is about scores Jaccard 0.15 — indistinguishable from
    unrelated. Every genuine cluster in the corpus looked like this.
    """
    small = frozenset({"a", "b", "c", "d", "e"})
    large = frozenset({"a", "b", "f", "g", "h", "i", "j", "k", "l", "m"})

    assert jaccard(small, large) < 0.2
    assert containment(small, large) == pytest.approx(0.4)


def test_containment_falls_back_to_jaccard_for_tiny_sets() -> None:
    """Otherwise one shared entity out of one is a perfect match."""
    assert containment(frozenset({"a"}), frozenset({"a", "b", "c"})) < 1.0


def test_missing_topics_do_not_count_as_disagreement() -> None:
    """39% of enriched items carry no topic at all.

    Scoring absence as dissimilarity would penalise exactly the items the
    pipeline knows least about, so the term is dropped and the remaining
    weights renormalised.
    """
    with_topics = make("Mistral Small 4 发布", topics={"llm"}, source_id="a", organization="A")
    without = make("Mistral Small 4 发布", topics=set(), source_id="b", organization="B")
    both_without = make("Mistral Small 4 发布", topics=set(), source_id="c", organization="C")

    paired = score_pair(without, both_without).total
    mixed = score_pair(with_topics, without).total

    # Identical titles and entities: dropping an unavailable term must not make
    # the pair look less alike than one where the term happens to be present.
    assert paired == pytest.approx(mixed, abs=0.01)


# --- the DeepSeek case ----------------------------------------------------


def _deepseek_event() -> list[Candidate]:
    shared = {"deepseek", "v4flash"}
    return [
        make(
            "DeepSeek-V4-Flash 正式版 API 上线公测",
            source_id="deepseek-changelog",
            organization="DeepSeek",
            content_type="api_update",
            entities=shared,
            hours=0,
        ),
        make(
            "DeepSeek V4-Flash 发布，性能跃升引发行业热议",
            source_id="latent-space",
            organization="Latent Space",
            tier="expert",
            content_type="model_release",
            entities=shared,
            hours=-4,
        ),
        make(
            "DeepSeek 发布 V4-Flash-0731 模型，性价比超越竞品",
            source_id="simon-willison",
            organization="Simon Willison",
            tier="expert",
            content_type="model_release",
            entities=shared,
            hours=-20,
        ),
    ]


def test_one_event_across_three_outlets_merges() -> None:
    groups, _ = cluster(_deepseek_event())
    assert len(groups) == 1
    assert len(groups[0].members) == 3


def test_merged_event_counts_three_independent_sources() -> None:
    """This is the number the hot list needs and could not compute before M3."""
    groups, _ = cluster(_deepseek_event())
    assert independent_sources(groups[0].members) == 3


def test_unrelated_release_that_merely_mentions_the_model_stays_out() -> None:
    """llama.cpp shares the DeepSeek entity but is not about DeepSeek."""
    members = _deepseek_event()
    members.append(
        make(
            "llama.cpp b10217 发布：为 DeepSeek 启用工具调用",
            source_id="llama-cpp",
            organization="ggml",
            entities={"deepseek", "llamacpp", "ggml", "tooling"},
            hours=-2,
        )
    )
    groups, _ = cluster(members)
    assert len(groups) == 2

    biggest = max(groups, key=lambda g: len(g.members))
    assert all("llama" not in m.title for m in biggest.members)


def test_previous_generation_model_forms_its_own_story() -> None:
    members = _deepseek_event()
    members.append(
        make(
            "DeepSeek-V3 发布：高效 MoE 模型，性能比肩闭源",
            source_id="deepseek-repo",
            organization="DeepSeek",
            entities={"deepseek", "v3"},
            hours=-30,
        )
    )
    groups, _ = cluster(members)
    v3 = [g for g in groups if any("V3" in m.title for m in g.members)]
    assert len(v3) == 1
    assert len(v3[0].members) == 1


# --- primary source -------------------------------------------------------


def test_official_announcement_outranks_expert_commentary() -> None:
    """docs/spec/03 §8: 官方当事方 > … > 技术作者."""
    groups, _ = cluster(_deepseek_event())
    primary = groups[0].primary()
    assert primary.source_id == "deepseek-changelog"


def test_announcement_outranks_opinion_within_one_tier() -> None:
    announcement = make("X 发布", content_type="model_release", tier="primary")
    opinion = make("X 观感", content_type="opinion", tier="primary")
    assert primary_rank(announcement) < primary_rank(opinion)


def test_unknown_tier_ranks_last() -> None:
    known = make("A", tier="secondary")
    unknown = make("B", tier="")
    assert primary_rank(known) < primary_rank(unknown)


# --- independence counting ------------------------------------------------


def test_two_feeds_from_one_company_are_not_independent() -> None:
    """Otherwise a vendor with a blog and a release feed self-corroborates."""
    members = [
        make("A", source_id="openai-blog", organization="OpenAI"),
        make("B", source_id="openai-releases", organization="OpenAI"),
    ]
    assert independent_sources(members) == 1


def test_sources_without_an_organisation_count_separately() -> None:
    members = [
        make("A", source_id="a", organization=None),
        make("B", source_id="b", organization=None),
    ]
    assert independent_sources(members) == 2


# --- time proximity -------------------------------------------------------


def test_simultaneous_items_score_full_proximity() -> None:
    assert time_proximity(BASE, BASE) == 1.0


def test_items_outside_the_window_score_zero() -> None:
    assert time_proximity(BASE, BASE + timedelta(hours=73)) == 0.0


def test_missing_timestamps_score_neutral_not_zero() -> None:
    """Several changelog sources publish without a date; zero would make their
    events permanently un-clusterable."""
    assert time_proximity(None, BASE) == 0.5


# --- scoring invariants ---------------------------------------------------


def test_score_is_bounded() -> None:
    left = make("完全相同的标题 v1")
    right = make("完全相同的标题 v1")
    assert 0.0 <= score_pair(left, right).total <= 1.0


def test_identical_items_score_above_the_merge_threshold() -> None:
    left = make("Mistral Small 4 发布：统一推理与多模态")
    right = make("Mistral Small 4 发布：统一推理与多模态", source_id="other", organization="Other")
    assert score_pair(left, right).total >= MERGE_THRESHOLD


def test_unrelated_items_score_below_the_suggestion_threshold() -> None:
    left = make("Mistral Small 4 发布", entities={"mistral"}, topics={"llm"})
    right = make(
        "欧盟通过人工智能法案实施细则",
        entities={"eu"},
        topics={"regulation"},
        content_type="policy",
        source_id="other",
        organization="Other",
    )
    assert score_pair(left, right).total < SUGGEST_THRESHOLD


def test_thresholds_leave_a_review_band() -> None:
    assert SUGGEST_THRESHOLD < MERGE_THRESHOLD


def test_every_weighted_feature_is_reported() -> None:
    """A feature silently missing from the breakdown cannot be audited."""
    from ahr.processing.story import FEATURE_WEIGHTS

    score = score_pair(make("A 发布 v1"), make("B 发布 v2", source_id="x"))
    assert set(score.features) == set(FEATURE_WEIGHTS)


# --- chaining -------------------------------------------------------------


def test_complete_linkage_prevents_chained_merges() -> None:
    """A weakly matches B and B weakly matches C, but A and C are unrelated.

    Single linkage would merge all three into one story; complete linkage scores
    a joiner against every member and rejects on the weakest pair.
    """
    a = make("Mistral Small 4 发布", entities={"mistral"}, source_id="a", organization="A")
    b = make(
        "Mistral 与 Cohere 同日发布新模型",
        entities={"mistral", "cohere"},
        source_id="b",
        organization="B",
    )
    c = make("Cohere Command A+ 发布", entities={"cohere"}, source_id="c", organization="C")

    groups, _ = cluster([a, b, c])
    assert not any(len(group.members) == 3 for group in groups)


# --- slugs ----------------------------------------------------------------


def test_slug_keeps_latin_words_and_is_unique() -> None:
    first = slugify("Mistral Small 4 Released", BASE)
    second = slugify("Mistral Small 4 Released", BASE)
    assert first.startswith("20260801-mistral-small-4-released")
    assert first != second


def test_slug_for_a_cjk_title_still_has_a_date_prefix() -> None:
    slug = slugify("深度求索发布新模型", BASE)
    assert slug.startswith("20260801-")

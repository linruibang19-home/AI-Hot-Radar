"""§6's `directness` and `source_fit`.

The two reranker dimensions the cross-encoder cannot supply. Both are bounded
metadata adjustments, so the tests that matter are the ones about *bounds* —
B3's first run turned a ±0.05 boost into the ranking function by applying it to
scores whose whole spread was 0.008.
"""

from __future__ import annotations

from ahr.rag.dimensions import (
    DIRECTNESS_WEIGHT,
    SOURCE_AFFINITY,
    SOURCE_FIT_WEIGHT,
    Candidate,
    apply_dimensions,
    directness,
    identifier_fit,
    identifiers,
    source_fit,
    tokenize,
)


def test_a_length_floor_must_not_delete_chinese() -> None:
    """A blanket `len >= 2` drops every CJK character, because CJK tokenizes one
    per character — `directness` would then score exactly 0.0 for every Chinese
    question and nothing would look broken. B2 found the same shape of failure
    when the sparse channel returned nothing for 15 pure-Chinese questions."""
    assert directness("智谱发布新模型", "智谱发布 GLM-5") > 0


# --- directness ------------------------------------------------------------


def test_a_title_about_the_subject_scores_above_one_that_mentions_it() -> None:
    """The B1 failure this exists for: asking which model uses MXFP4 returned
    vLLM's release notes above the model that actually uses it. Both passages
    contain the token; only one document is about it."""
    question = "使用 MXFP4 量化的是哪个模型"
    about = directness(question, "Kimi K3 模型概览：2.8T 参数与 MXFP4 量化")
    mentions = directness(question, "vLLM v0.26.0 发布")

    assert about > mentions


def test_directness_is_a_share_and_stays_in_range() -> None:
    assert directness("MXFP4", "MXFP4 quantization") == 1.0
    assert directness("MXFP4", "unrelated release") == 0.0
    assert 0.0 <= directness("a b c MXFP4", "MXFP4") <= 1.0


def test_empty_question_is_neutral_not_a_division_by_zero() -> None:
    assert directness("", "any title") == 0.0
    assert directness("!!", "any title") == 0.0


def test_single_characters_do_not_count_as_terms() -> None:
    """Matching on one letter would make every title look direct."""
    assert "a" not in tokenize("a model")
    assert "模" in tokenize("模型")


def test_cjk_splits_per_character_and_latin_per_word() -> None:
    """The same rule the sparse channel uses — one tokenizer, both languages."""
    assert tokenize("智谱发布") == {"智", "谱", "发", "布"}
    assert "llama.cpp" in tokenize("llama.cpp b10223")


def test_identifiers_only_keep_mixed_model_or_version_tokens() -> None:
    assert identifiers("GLM-5.2 在 2026-08-03 发布") == {"glm-5.2"}
    assert identifiers("普通 model 和 2026-08-03") == set()


def test_identifier_fit_is_case_insensitive_and_bounded() -> None:
    assert identifier_fit("GLM-5.2 有什么 SLA", "Hosted glm-5.2 has 99% uptime") == 1.0
    assert identifier_fit("GLM-5.2 与 Qwen3.8-Max", "Only GLM-5.2 is here") == 0.5
    assert identifier_fit("没有显式型号", "GLM-5.2") == 0.0


# --- source_fit ------------------------------------------------------------


def test_a_release_note_is_poor_evidence_for_an_explainer() -> None:
    """The point of the affinity table. A changelog is a primary source and
    still a bad answer to "how does this work": it states, it does not
    explain."""
    assert source_fit("explainer", "primary") < 0
    assert source_fit("explainer", "expert") > 0


def test_a_release_note_is_the_best_evidence_for_recent_updates() -> None:
    assert source_fit("recent_updates", "primary") == 1.0
    assert source_fit("recent_updates", "primary") > source_fit("recent_updates", "community")


def test_an_unknown_tier_is_neutral_rather_than_penalised() -> None:
    """A missing tier is missing information. Penalising it would demote
    everything enrichment has not reached yet."""
    assert source_fit("fact_check", None) == 0.0
    assert source_fit("fact_check", "made_up_tier") == 0.0


def test_an_unknown_query_type_is_neutral() -> None:
    assert source_fit("something_new", "primary") == 0.0


def test_affinity_values_stay_within_the_declared_range() -> None:
    for row in SOURCE_AFFINITY.values():
        assert all(-1.0 <= value <= 1.0 for value in row.values())


# --- the combined adjustment -----------------------------------------------


def _candidate(key: str, relevance: float, title: str, tier: str = "primary") -> Candidate:
    return Candidate(key=key, relevance=relevance, title=title, source_tier=tier)


def test_relevance_still_dominates() -> None:
    """Bounded means bounded: a passage that plainly answers the question must
    not be overturned by metadata. Both adjustments together cap at 0.18 on a
    normalised [0, 1] score."""
    assert DIRECTNESS_WEIGHT + SOURCE_FIT_WEIGHT < 0.5

    clear_winner = _candidate("a", 10.0, "irrelevant title")
    metadata_darling = _candidate("b", 0.0, "MXFP4 量化")
    order = apply_dimensions(
        [clear_winner, metadata_darling], question="MXFP4", query_type="fact_check"
    )
    assert order[0] == "a"


def test_directness_breaks_a_tie_on_relevance() -> None:
    """Where it is meant to act: two passages the cross-encoder cannot separate,
    one from a document about the subject."""
    order = apply_dimensions(
        [
            _candidate("mentions", 0.9, "vLLM v0.26.0 发布"),
            _candidate("about", 0.9, "Kimi K3：MXFP4 量化"),
        ],
        question="MXFP4 量化",
        query_type="fact_check",
    )
    assert order[0] == "about"


def test_identifier_guard_can_break_a_cross_lingual_near_tie() -> None:
    order = apply_dimensions(
        [
            Candidate("nearby", 0.90, "智谱托管服务", "primary", "GLM family"),
            Candidate("exact", 0.90, "Provisioned Throughput", "primary", "GLM-5.2 SLA"),
        ],
        question="GLM-5.2 的可用性承诺是什么",
        query_type="fact_check",
        identifier_fit_weight=0.12,
    )
    assert order[0] == "exact"


def test_source_fit_reorders_an_explainer_toward_the_expert_source() -> None:
    order = apply_dimensions(
        [
            _candidate("changelog", 0.9, "release notes", tier="primary"),
            _candidate("essay", 0.9, "release notes", tier="expert"),
        ],
        question="什么是 MoE 路由",
        query_type="explainer",
    )
    assert order[0] == "essay"


def test_a_flat_relevance_list_normalises_to_one_not_zero() -> None:
    """Collapsing ties to zero would hand the entire decision to the
    adjustments — the opposite of a bounded one. Same choice as temporal_fit."""
    order = apply_dimensions(
        [_candidate("x", 0.5, "t"), _candidate("y", 0.5, "t")],
        question="q",
        query_type="fact_check",
    )
    assert set(order) == {"x", "y"}


def test_order_is_reproducible_on_a_tie() -> None:
    """Two runs that differ for no reason would make a regression undiagnosable."""
    candidates = [_candidate("b", 0.5, "t"), _candidate("a", 0.5, "t")]
    assert apply_dimensions(candidates, question="q", query_type="fact_check") == ["a", "b"]


def test_no_candidates_is_not_an_error() -> None:
    assert apply_dimensions([], question="q", query_type="fact_check") == []


def test_every_candidate_survives_the_reorder() -> None:
    """A reordering that drops a passage would silently cut recall."""
    candidates = [_candidate(str(i), float(i), f"title {i}") for i in range(10)]
    order = apply_dimensions(candidates, question="title 3", query_type="fact_check")
    assert sorted(order) == sorted(c.key for c in candidates)


# --- production runs what the evaluation measured --------------------------


def test_the_served_pipeline_applies_every_evaluated_dimension() -> None:
    """B7 was measured, reported and marked shipped — and never wired into
    `service.py`. `recent_updates` MRR 0.6484 -> 0.7522 existed only inside the
    evaluation harness, so the number in the docs described a configuration no
    reader ever received. An evaluation that does not bind the served path is a
    press release."""
    import inspect

    from ahr.rag import service

    source = inspect.getsource(service.retrieve)
    assert "_rank_by_dimensions(" in source
    assert "_rank_by_recency(" in source


def test_the_served_pipeline_uses_the_evaluated_channel_set() -> None:
    """The B3/B9 reports include TEMPORAL_SQL whenever the plan has a window.

    Serving only dense+sparse made every reported retrieval metric describe a
    configuration no reader received.  Pin the channel call in both paths so a
    later refactor cannot recreate that split silently.
    """
    import inspect

    from ahr.rag import service
    from ahr.rag.eval import runner

    served = inspect.getsource(service.retrieve)
    scored = inspect.getsource(runner.rrf_retriever)
    for source in (served, scored):
        assert "temporal_search(" in source
        assert '"entity_temporal" if query_family_entities else "temporal"' in source


def test_dimensions_are_applied_before_the_unreranked_tail_is_appended() -> None:
    """Both evaluations reorder only the cross-encoder's output. Applying the
    dimensions to the merged list would also reorder candidates the reranker
    never scored — a configuration neither B7 nor B9 measured."""
    import inspect

    from ahr.rag import service

    source = inspect.getsource(service.retrieve)
    assert source.index("_rank_by_dimensions(") < source.index("taken = {")
    assert source.index("_rank_by_recency(") < source.index("taken = {")

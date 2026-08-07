"""Caching answers over a corpus that changes every two minutes (T3-6, ADR-0017).

The interesting properties here are all about *not* serving something. A cache
that returns yesterday's answer to "本周有什么动态" has not degraded gracefully —
it has given a wrong answer with full confidence, and faster than before.

So what is pinned is: the corpus fingerprint is part of the key, refusals never
enter the cache, the near-match threshold stays high, and a near-match from a
different corpus is never used.
"""

from __future__ import annotations

import inspect

from ahr.rag import cache, service


def _vector(*values: float) -> list[float]:
    return list(values)


# --- freshness is in the key, not in a TTL ---------------------------------


def test_the_corpus_fingerprint_is_part_of_the_answer_key() -> None:
    """The whole design. A TTL would be a bet on how often the corpus changes;
    ingestion polls every 120 seconds, so that bet loses."""
    before = cache.answer_key("本周有什么动态", fingerprint="aaa", prompt_version="v2")
    after = cache.answer_key("本周有什么动态", fingerprint="bbb", prompt_version="v2")

    assert before != after


def test_a_prompt_change_also_invalidates() -> None:
    """The answer's shape is a function of the prompt. Reusing an entry across
    prompt versions would show the old format under the new contract."""
    v2 = cache.answer_key("问题", fingerprint="aaa", prompt_version="rag-answer-v2")
    v3 = cache.answer_key("问题", fingerprint="aaa", prompt_version="rag-answer-v3")

    assert v2 != v3


def test_the_fingerprint_tracks_embedded_chunks_not_items() -> None:
    """An item that exists but was never chunked cannot be retrieved, so it
    cannot change an answer — invalidating on it would throw entries away for
    nothing."""
    source = inspect.getsource(cache.corpus_fingerprint)
    assert "content_chunk" in source
    assert "embedding IS NOT NULL" in source


# --- canonicalisation stays conservative ------------------------------------


def test_only_case_and_whitespace_are_normalised() -> None:
    assert cache.canonical("  DeepSeek   有什么 动态 ") == cache.canonical("deepseek 有什么 动态")


def test_word_order_still_makes_a_different_question() -> None:
    """Stemming or stop-word removal would quietly turn an exact cache into a
    fuzzy one, and these two questions have different answers."""
    left = cache.canonical("DeepSeek V3 和 V4 的区别")
    right = cache.canonical("DeepSeek V4 和 V3 的区别")

    assert left != right


# --- refusals are never cached ---------------------------------------------


class _Redis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)


async def _put(payload: dict[str, object]) -> _Redis:
    client = _Redis()
    await cache.put_answer(client, "k", payload)  # type: ignore[arg-type]
    return client


def test_a_refusal_is_not_stored() -> None:
    """A refusal means "the corpus does not contain this **yet**" — the most
    time-dependent thing the system says. Cached, it keeps saying no after the
    answer arrives."""
    import asyncio

    client = asyncio.run(_put({"refused": True, "answerMarkdown": ""}))
    assert client.store == {}

    stored = asyncio.run(_put({"refused": False, "answerMarkdown": "答案"}))
    assert "k" in stored.store


# --- the near-match threshold ----------------------------------------------


def test_the_similarity_threshold_is_conservative() -> None:
    """0.97, not the 0.85 a demo would pick. On this corpus a loose threshold
    does not return a slightly worse answer — it answers about a different
    company, confidently."""
    assert cache.SEMANTIC_THRESHOLD >= 0.95


def test_cosine_is_one_for_the_same_vector_and_zero_for_orthogonal() -> None:
    assert cache.cosine(_vector(1, 0, 0), _vector(1, 0, 0)) == 1.0
    assert cache.cosine(_vector(1, 0, 0), _vector(0, 1, 0)) == 0.0


def test_mismatched_dimensions_score_zero_rather_than_raising() -> None:
    """A model change leaves old vectors of the wrong width in the index. They
    must be ignored, not crash the lookup."""
    assert cache.cosine(_vector(1, 0), _vector(1, 0, 0)) == 0.0


def test_a_near_match_from_a_different_corpus_is_skipped() -> None:
    source = inspect.getsource(cache.semantic_lookup)
    # Skipped before scoring: an identical question can still deserve a
    # different answer once the corpus has moved.
    assert 'record.get("fingerprint") != fingerprint' in source
    assert source.index('record.get("fingerprint")') < source.index("cosine(")


def test_the_near_match_index_is_bounded() -> None:
    """An unbounded index is an unbounded way to serve an old answer, and the
    lookup is a linear scan."""
    assert cache.SEMANTIC_INDEX_SIZE <= 500
    assert "ltrim" in inspect.getsource(cache.semantic_remember)


# --- the cache never breaks the feature -------------------------------------


def test_every_redis_call_is_guarded() -> None:
    """Redis is a cache, not a source of truth (ADR-005). An outage must cost
    latency and money, never an error page."""
    for name in (
        "get_embedding",
        "put_embedding",
        "get_answer",
        "put_answer",
        "semantic_lookup",
        "semantic_remember",
        "record",
        "stats",
    ):
        source = inspect.getsource(getattr(cache, name))
        assert "except Exception" in source, name


# --- integration with the answer path ---------------------------------------


def test_the_exact_lookup_happens_before_any_provider_call() -> None:
    """Layer 1 is checked before embedding, so a repeat question costs zero
    external round trips rather than one."""
    source = inspect.getsource(service._from_cache)
    assert source.index("get_answer(") < source.index("embedder.embed(")


def test_a_semantic_miss_still_hands_its_vector_onward() -> None:
    """Otherwise every miss pays for the same embedding twice — once to look in
    the cache, once inside `retrieve`."""
    assert "state.vector = vector" in inspect.getsource(service._from_cache)
    assert "query_vector=cache_state.vector" in inspect.getsource(service.answer_question)


def test_a_cached_answer_serialises_through_the_same_path_as_a_fresh_one() -> None:
    """Citations are rehydrated into real `Citation` objects rather than passed
    through as dicts. A second serialisation path is how the cached copy starts
    to differ from the live one without anyone noticing."""
    source = inspect.getsource(service._replay)
    assert "Citation(" in source


def test_a_cache_hit_keeps_the_original_query_id() -> None:
    """A hit *is* that answer. Its permalink already holds the trace and the
    citations that explain it; minting a new id would point at nothing."""
    source = inspect.getsource(service._replay)
    assert 'answer.query_id = payload.get("queryId")' in source


# --- granularity follows the planner ----------------------------------------


def test_a_time_sensitive_question_binds_to_the_exact_corpus() -> None:
    """These are the questions where a stale answer is wrong rather than old,
    so they should miss whenever anything arrived. That cost is the point."""
    source = inspect.getsource(cache.corpus_fingerprint)
    assert "if freshness_required:" in source
    assert '_digest("exact"' in source


def test_an_explainer_question_is_not_invalidated_by_unrelated_news() -> None:
    """The first version pinned everything to the exact corpus. Provably
    correct, and useless: ingestion polls every 120s, so a question repeated a
    minute later already missed — measured as 92e5b821 then b8518432."""
    source = inspect.getsource(cache.corpus_fingerprint)
    assert '_digest("daily"' in source


def test_the_two_granularities_cannot_collide() -> None:
    """Tagged, so a daily key can never be mistaken for an exact one that
    happens to hash the same inputs."""
    source = inspect.getsource(cache.corpus_fingerprint)
    assert source.index('"exact"') < source.index('"daily"')


def test_the_cache_asks_the_planner_rather_than_guessing() -> None:
    """`freshness_required` already exists and already gates the retrieval time
    filter. Re-deriving "is this time sensitive" here would be a second answer
    to a question the system had settled."""
    source = inspect.getsource(service._from_cache)
    assert "build_plan(" in source
    assert "freshness_required=plan.freshness_required" in source


# --- a cached answer is a complete answer -----------------------------------


def test_a_cached_answer_keeps_its_retrieval_plan() -> None:
    """Dropping it lost the query type and the resolved window — the two things
    that show a reader "最近" became a real interval. A browser test caught it:
    the plan chips simply stopped rendering on a cache hit."""
    from ahr.rag.planner import plan as build_plan

    original = build_plan("llama.cpp 最近发布了哪些版本？")
    replayed = service._replay(
        {"answerMarkdown": "答案[1]", "plan": original.as_dict(), "citations": []},
        outcome="exact",
        similarity=None,
    )

    assert replayed.plan is not None
    assert replayed.plan.query_type == original.query_type
    assert replayed.plan.freshness_required == original.freshness_required
    assert replayed.plan.time_range is not None
    assert replayed.plan.time_range.start == original.time_range.start


def test_a_malformed_plan_degrades_to_no_plan_rather_than_an_error() -> None:
    """This is reading back a cache entry. A bad one should cost the plan
    display, never the request."""
    from ahr.rag.planner import plan_from_dict

    assert plan_from_dict(None) is None
    assert plan_from_dict({}) is None
    assert plan_from_dict({"asked_at": "not-a-date"}) is None


# --- the cache must not contaminate or be measured by the evaluations -------


def test_an_unrecorded_answer_is_not_cached() -> None:
    """The evaluation runs with `persist=False` so it leaves no synthetic rows
    in `rag_query`. Storing those answers in the cache anyway would leave 90
    entries behind instead — each carrying a null `queryId`, so a later visitor
    hitting one would receive an answer whose permalink points at nothing."""
    source = inspect.getsource(service.answer_question)
    store = source.index("_store_in_cache(")
    guard = source.index("if persist:")

    assert guard < store
    # And it is inside that block, not merely after it: same indentation as the
    # persistence calls it belongs with.
    line = next(ln for ln in source.splitlines() if "_store_in_cache(" in ln and "await" in ln)
    assert line.startswith(" " * 12), line


def test_both_evaluations_measure_the_pipeline_rather_than_the_cache() -> None:
    """A cache hit answers in ~200ms and replays a stored answer. Measured, it
    would report a p50 the pipeline never achieved and a groundedness this run
    did not produce."""
    from ahr.rag.eval import generation, latency

    for module in (generation, latency):
        assert "bypass_cache=True" in inspect.getsource(module)

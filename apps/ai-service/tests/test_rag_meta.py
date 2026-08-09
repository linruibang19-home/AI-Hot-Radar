"""Questions about the site, routed away from the index (Phase B-2).

「现在有什么信源？」 was answered with four llama.cpp release notes and a confident
summary of the download links in them. Retrieval always returns a top-k, so a
question the corpus cannot answer comes back looking exactly like one it can.
"""

from __future__ import annotations

import inspect

from ahr.rag import meta, service


def test_the_questions_that_caused_this() -> None:
    """Both shapes seen live, plus the ones a first visitor types next."""
    for question in (
        "现在有什么信源？",
        "这个网站现在收录了多少条内容？",
        "数据从哪来的？",
        "多久更新一次？",
        "有哪些数据源",
    ):
        assert meta.looks_like_meta(question), question


def test_a_question_about_the_news_is_not_meta() -> None:
    """A loose pattern diverts real questions into a corpus summary, which is
    confidently off-topic and gives the reader no sign it happened. That is a
    worse failure than the one being fixed, so the patterns stay narrow."""
    for question in (
        "最近 llama.cpp 发布了哪些版本？",
        "Qwen3.8-Max 的参数量是多少？",
        "MoE 路由是怎么工作的？",
        "智谱最近发布了什么？",
    ):
        assert not meta.looks_like_meta(question), question


def test_naming_a_vendor_takes_it_out_of_meta_scope() -> None:
    """「有哪些信源」 is about the site; 「OpenAI 有哪些信源」 is about OpenAI.

    The wording alone cannot separate them, so the served path also requires
    that the question resolves no corpus entity — reusing the resolver the §6
    boosts use rather than inventing a second notion of naming a thing.
    """
    assert meta.looks_like_meta("OpenAI 有哪些信源？")

    source = inspect.getsource(service.answer_question)
    guard = source[source.index("looks_like_meta(") :].split("\n")[0]
    assert "not resolve_query_entities(" in guard


def test_the_stats_answer_is_not_a_refusal_and_carries_no_citations() -> None:
    """`refused` means the corpus could not support an answer. This one is
    supported, by something that is not the corpus — so it needs its own kind
    rather than either of the two existing outcomes."""
    source = inspect.getsource(service.answer_question)
    branch = source[source.index("looks_like_meta(") : source.index("cached, cache_state")]

    assert 'kind="corpus_stats"' in branch
    assert "refused=False" in branch
    assert "citations=[]" in branch


def test_it_runs_before_retrieval_and_before_the_cache() -> None:
    """Retrieval cannot answer it and the cache would key it like any other
    question. Both are wasted work, and the first one is the actual bug."""
    source = inspect.getsource(service.answer_question)
    assert source.index("looks_like_meta(") < source.index("cached, cache_state")
    assert source.index("looks_like_meta(") < source.index("await retrieve(")


def test_the_numbers_are_counted_not_generated() -> None:
    """A model asked how many sources the site has would invent a plausible
    number, which is the failure this module exists to remove."""
    assert "count(*)" in inspect.getsource(meta.load_corpus_facts)
    composed = inspect.getsource(meta.compose)
    assert "llm" not in composed.lower()


def test_the_answer_says_it_is_not_a_retrieval_result() -> None:
    """The page's promise is that every fact carries a source. This answer has
    none, so it has to say why rather than look like an answer that lost them."""
    facts = meta.CorpusFacts(
        items=1553, active_sources=107, chunks=6349, enriched=1463, newest=None, oldest=None
    )
    body = meta.compose(facts, [("llama.cpp Releases", 100)])

    assert "1553" in body
    assert "107" in body
    assert "llama.cpp Releases" in body

"""Latin product names typed inline in Chinese must reach the sparse channel.

Found by a reader noticing the trace always said "60 条候选" — a suspiciously
round number that turned out to be the dense channel's `topK` exactly, because
the sparse channel was returning zero.

Postgres's `simple` parser splits on whitespace and punctuation, not on script
changes, so `最近grok有什么动态吗` becomes one lexeme with zero corpus frequency.
Dense retrieval still returned its 60, so the answer looked reasonable while
running on one channel instead of two.
"""

from __future__ import annotations

from ahr.rag.retrieval import split_scripts


def test_latin_inline_in_chinese_is_separated() -> None:
    assert split_scripts("最近grok有什么动态吗") == "最近 grok 有什么动态吗"


def test_separation_happens_in_both_directions() -> None:
    assert split_scripts("grok最近") == "grok 最近"
    assert split_scripts("最近grok") == "最近 grok"


def test_text_that_is_already_spaced_is_unchanged() -> None:
    """The channel worked for these all along; the fix must not disturb them."""
    assert split_scripts("llama.cpp 最近发布了哪些版本") == "llama.cpp 最近发布了哪些版本"
    assert split_scripts("使用 MXFP4 量化的是哪个模型") == "使用 MXFP4 量化的是哪个模型"


def test_pure_latin_and_pure_chinese_are_untouched() -> None:
    assert split_scripts("what changed in vLLM") == "what changed in vLLM"
    assert split_scripts("最近有哪些新动态") == "最近有哪些新动态"


def test_digits_glued_to_chinese_separate() -> None:
    # Version numbers are the other half of this corpus's vocabulary.
    assert split_scripts("Grok4.5发布了吗") == "Grok4.5 发布了吗"


def test_internal_punctuation_in_a_name_survives() -> None:
    """`llama.cpp` must stay one token — splitting it would trade one silent
    miss for another."""
    assert "llama.cpp" in split_scripts("llama.cpp有什么更新")


def test_empty_input_is_safe() -> None:
    assert split_scripts("") == ""

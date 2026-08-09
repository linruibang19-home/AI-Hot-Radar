"""Follow-up suggestions (Phase C UX).

Multi-turn works and nothing invited a second turn — the reader had to think of
one and type it.
"""

from __future__ import annotations

import inspect

from ahr.rag import suggest as suggest_module
from ahr.rag.suggest import MAX_SUGGESTION_CHARS, MAX_SUGGESTIONS, _parse


def test_it_keeps_three_short_questions() -> None:
    rows = _parse(
        '["Kimi K3 的上下文有多长？", "Kimi K3 什么时候开源？", "谁在用 MXFP4？"]', asked="x"
    )
    assert rows == ["Kimi K3 的上下文有多长？", "Kimi K3 什么时候开源？", "谁在用 MXFP4？"]
    assert len(rows) <= MAX_SUGGESTIONS


def test_a_paragraph_is_not_a_chip() -> None:
    """A suggestion that wraps to three lines is a paragraph pretending to be a
    button."""
    long_one = "这" * (MAX_SUGGESTION_CHARS + 1)
    assert _parse(f'["{long_one}", "短问题？"]', asked="x") == ["短问题？"]


def test_it_never_suggests_the_question_just_asked() -> None:
    """Wastes a slot and looks broken."""
    assert _parse(
        '["Kimi K3 的参数量是多少？", "别的问题？"]', asked="Kimi K3 的参数量是多少？"
    ) == ["别的问题？"]


def test_duplicates_collapse() -> None:
    assert _parse('["同一个？", "同一个？", "另一个？"]', asked="x") == ["同一个？", "另一个？"]


def test_an_unusable_reply_yields_nothing_rather_than_a_guess() -> None:
    """The feature is optional; a malformed reply is not worth repairing into
    something the corpus may not answer."""
    for reply in ("not json", '{"suggestions": []}', "", "```\nnope\n```"):
        assert _parse(reply, asked="x") == []


def test_a_fenced_array_is_still_read() -> None:
    assert _parse('```json\n["问题一？"]\n```', asked="x") == ["问题一？"]


def test_suggestions_are_grounded_in_what_was_cited() -> None:
    """A suggestion the corpus cannot answer is worse than none: the reader
    clicks it, gets a refusal, and learns the chips are decoration."""
    source = inspect.getsource(suggest_module._context)
    assert "rag_citation" in source
    assert "content_item" in source

    prompt = suggest_module.SYSTEM_PROMPT
    assert "不要提这些文档里没有的内容" in prompt


def test_an_answer_with_no_citations_gets_no_suggestions() -> None:
    """A refusal has nothing to build on, and inventing follow-ups for it would
    be the exact failure the grounding rule exists to prevent."""
    source = inspect.getsource(suggest_module.suggest)
    assert "if not asked or not titles:" in source
    assert "return []" in source


def test_it_is_not_on_the_answer_s_critical_path() -> None:
    """p50 is ~10s of external round trips; a fourth would make the answer
    slower to buy something the reader has not asked for yet."""
    from ahr.rag import service

    assert "suggest" not in inspect.getsource(service.answer_question)

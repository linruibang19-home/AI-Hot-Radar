"""Reasoning models put their chain of thought in front of the answer.

Every structured call site in this codebase ends in `model_validate_json` or
`json.loads`, so a `<think>…</think>` prefix turns a correct answer into a
schema failure and the caller degrades to its no-model path. The strings in the
first test are the real response measured against MiniMax-M3 on 2026-08-29 with
`response_format: {"type": "json_object"}` set and `finish_reason: stop` — the
transport-level JSON contract does not suppress the block.
"""

from __future__ import annotations

import httpx
import pytest

from ahr.processing.llm import (
    LlmClient,
    LlmConfig,
    TokenUsage,
    _ReasoningPrefixFilter,
    strip_reasoning_prefix,
)

MEASURED = (
    "<think>The user wants a one-sentence summary of today's AI industry "
    'changes, output as strict JSON with only a "summary" field.</think>\n\n'
    '{"summary":"今日 AI 行业的主要变化是……"}'
)


def _client(handler) -> LlmClient:
    return LlmClient(
        LlmConfig(base_url="https://llm.example", api_key="k", model="m", max_attempts=1),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_strips_the_measured_minimax_response() -> None:
    assert strip_reasoning_prefix(MEASURED) == '{"summary":"今日 AI 行业的主要变化是……"}'


@pytest.mark.parametrize("tag", ["think", "thinking", "reasoning", "THINK", "Thinking"])
def test_strips_every_spelling_of_the_block(tag: str) -> None:
    assert strip_reasoning_prefix(f"<{tag}>weighing options</{tag}>\n\n答案") == "答案"


def test_leaves_a_plain_response_untouched() -> None:
    """The overwhelmingly common case must cost nothing and change nothing."""
    assert strip_reasoning_prefix('{"summary":"直接回答"}') == '{"summary":"直接回答"}'


def test_does_not_touch_the_literal_tag_inside_the_answer() -> None:
    """A summary of an article *about* reasoning models is not a reasoning block.

    This is why the pattern is anchored to the start of the response: a global
    strip would silently corrupt the field.
    """
    payload = '{"summary":"该模型用 <think>思考</think> 标记推理过程。"}'
    assert strip_reasoning_prefix(payload) == payload


def test_an_unterminated_block_yields_nothing() -> None:
    """Budget ran out mid-thought, so the response contains no answer at all.

    Returning the reasoning prose would fail validation with a misleading error;
    the empty string fails it for the true reason.
    """
    assert strip_reasoning_prefix("<think>still deciding, ran out of tokens") == ""


async def test_summarize_hands_the_caller_parseable_json() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": MEASURED}}]})

    async with _client(handler) as client:
        text, _ = await client.summarize(system_prompt="s", user_prompt="u", json_mode=True)

    import json

    assert json.loads(text)["summary"].startswith("今日")


def test_stream_filter_survives_a_tag_split_across_deltas() -> None:
    """Providers split tokens wherever they like; `<thi` + `nk>` is routine."""
    stream = _ReasoningPrefixFilter()
    pieces = ["<thi", "nk>wei", "ghing", "</thin", "k>\n\n", '{"a":', "1}"]
    out = "".join(stream.feed(piece) for piece in pieces) + stream.finish()
    assert out == '{"a":1}'


def test_stream_filter_forwards_a_plain_stream() -> None:
    stream = _ReasoningPrefixFilter()
    out = "".join(stream.feed(piece) for piece in ["答", "案", "在此"]) + stream.finish()
    assert out == "答案在此"


def test_stream_filter_emits_nothing_when_the_block_never_closes() -> None:
    stream = _ReasoningPrefixFilter()
    out = "".join(stream.feed(piece) for piece in ["<think>", "still ", "thinking"])
    assert out + stream.finish() == ""


async def test_stream_summarize_does_not_leak_reasoning_to_the_browser() -> None:
    """`/rag/ask/stream` renders these deltas directly; the block must not reach it."""

    def handler(_: httpx.Request) -> httpx.Response:
        frames = (
            'data: {"choices":[{"delta":{"content":"<think>"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"planning"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"</think>\\n\\n"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"{\\"answer_markdown\\":\\"答案\\"}"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=frames, headers={"content-type": "text/event-stream"})

    usage = TokenUsage()
    async with _client(handler) as client:
        pieces = [
            piece
            async for piece in client.stream_summarize(
                system_prompt="s", user_prompt="u", usage=usage, json_mode=True
            )
        ]

    assert "".join(pieces) == '{"answer_markdown":"答案"}'

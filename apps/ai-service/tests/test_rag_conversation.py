"""Follow-up questions (Phase C, AHR-RAG-400 §11).

Asked 「它的参数量呢？」 the system answered 「没有单一模型被明确指定为"它"」 — correctly,
because nothing carried the previous turn. `rag_query.conversation_id` existed
since V001 and was written by nothing.
"""

from __future__ import annotations

import inspect

from ahr.processing.llm import LlmUnavailableError
from ahr.rag import conversation, service
from ahr.rag.conversation import MAX_REWRITE_CHARS, Turn, rewrite


class _Llm:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls = 0

    async def summarize(self, *, system_prompt: str, user_prompt: str) -> tuple[str, object]:
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, object()


_TURNS = [Turn(question="Qwen3.8-Max 的参数量是多少？", cited_titles=("阿里发布 Qwen3.8-Max",))]


async def test_a_pronoun_is_resolved_into_a_standalone_query() -> None:
    llm = _Llm("Qwen3.8-Max 的上下文长度是多少？")
    text, changed = await rewrite(llm, "它的上下文长度呢？", _TURNS)

    assert changed is True
    assert text == "Qwen3.8-Max 的上下文长度是多少？"


async def test_the_first_turn_costs_no_model_call() -> None:
    """Most questions are not follow-ups, and a rewrite with nothing to resolve
    is a round trip spent restating the question."""
    llm = _Llm("should not be called")
    text, changed = await rewrite(llm, "最近有什么动态？", [])

    assert (text, changed) == ("最近有什么动态？", False)
    assert llm.calls == 0


async def test_a_provider_wobble_falls_back_to_the_question_as_typed() -> None:
    """A follow-up answered without context is a worse answer; one that errors
    is no answer."""
    llm = _Llm(LlmUnavailableError("timeout"))
    text, changed = await rewrite(llm, "它呢？", _TURNS)

    assert (text, changed) == ("它呢？", False)


async def test_an_answer_in_place_of_a_rewrite_is_rejected() -> None:
    """Seen in prompt testing: the model answers instead of restating. A
    paragraph reaching the retriever would search for its guess."""
    llm = _Llm("Qwen3.8-Max 的参数量是 2.4 万亿。" * 40)
    text, changed = await rewrite(llm, "它呢？", _TURNS)

    assert changed is False
    assert text == "它呢？"
    assert len("Qwen3.8-Max 的参数量是 2.4 万亿。" * 40) > MAX_REWRITE_CHARS


async def test_an_empty_rewrite_is_rejected() -> None:
    text, changed = await rewrite(_Llm("   "), "它呢？", _TURNS)
    assert (text, changed) == ("它呢？", False)


def test_the_rewriter_never_sees_a_previous_answer() -> None:
    """§11: facts are re-retrieved each turn and a previous answer is never a
    new fact. An antecedent existing only inside generated prose is one this
    deliberately cannot resolve — recovering it would launder an unverified
    claim into the next query.
    """
    source = inspect.getsource(conversation.load_turns)
    assert "answer_markdown" not in source
    # What it does select — document titles — are corpus facts with a source.
    assert "ci.title" in source

    fields = {f for f in Turn.__dataclass_fields__}
    assert fields == {"question", "cited_titles"}


def test_rewriting_happens_before_retrieval_not_in_the_prompt() -> None:
    """Retrieval runs before generation, so resolving the pronoun in the
    generation prompt would leave the retriever searching 「它呢」 — a query with
    no content words that the sparse channel drops entirely."""
    source = inspect.getsource(service.answer_question)
    assert source.index("await rewrite(") < source.index("await retrieve(")


def test_the_transcript_is_bounded() -> None:
    """§11 asks for the recent transcript, not the session. Long enough for a
    pronoun, short enough that the rewrite cannot drift into summarising."""
    assert conversation.MAX_TURNS <= 10
    assert "LIMIT %s" in inspect.getsource(conversation.load_turns)


def test_the_stored_question_is_the_one_the_reader_typed() -> None:
    """Storing the rewrite as *the* question shows a reader their own history
    containing a sentence they never wrote, and leaves nothing to compare
    against when an answer looks wrong.

    Seen in the first live two-turn test: `rag_query.question` read
    「Qwen3.8-Max 的上下文长度是多少？」 for a turn typed as 「它的上下文长度呢？」.
    """
    source = inspect.getsource(service.answer_question)
    assert "asked = question" in source
    assert "question=asked," in source


def test_the_next_turn_still_sees_the_resolved_name() -> None:
    """Keeping the typed question must not cost the chain: 「它呢」 then
    「那它的价格呢」 only resolves if the middle turn contributes the name."""
    assert "retrieval_plan->>'question'" in inspect.getsource(conversation.load_turns)

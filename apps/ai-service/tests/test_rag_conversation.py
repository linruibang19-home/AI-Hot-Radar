"""Follow-up questions (Phase C, AHR-RAG-400 §11).

Asked 「它的参数量呢？」 the system answered 「没有单一模型被明确指定为"它"」 — correctly,
because nothing carried the previous turn. `rag_query.conversation_id` existed
since V001 and was written by nothing.
"""

from __future__ import annotations

import inspect
import json

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


# --- the transcript cache ---------------------------------------------------


class _Cache:
    """Enough Redis to exercise the transcript layer, and a call log."""

    def __init__(self, stored: dict[str, str] | None = None) -> None:
        self.stored = stored or {}
        self.reads: list[str] = []
        self.writes: list[tuple[str, str, int | None]] = []

    async def get(self, key: str) -> str | None:
        self.reads.append(key)
        return self.stored.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.writes.append((key, value, ex))
        self.stored[key] = value


class _DbCursor:
    def __init__(self, rows: list[tuple[object, ...]], log: list[str]) -> None:
        self.rows = rows
        self.log = log

    def __enter__(self) -> _DbCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = ()) -> None:
        self.log.append(sql)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _Db:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def cursor(self) -> _DbCursor:
        return _DbCursor(self.rows, self.queries)


_THREAD = "2c9a1d44-5c1f-4f8e-9c3d-7a1b2c3d4e5f"


async def test_a_warm_transcript_costs_no_database_query(monkeypatch) -> None:
    """The point of the layer. Every follow-up ran a five-table join to recover
    at most six short strings, on the request path, before retrieval started."""
    warm = json.dumps(
        [{"question": "Qwen3.8-Max 的参数量是多少？", "citedTitles": ["阿里发布 Qwen3.8-Max"]}],
        ensure_ascii=False,
    )
    cache = _Cache({f"ahr:rag:v1:thread:{_THREAD}": warm})
    monkeypatch.setattr(conversation, "cache_client", lambda: cache)
    db = _Db([])

    turns = await conversation.turns_for(db, _THREAD)

    assert turns == [
        Turn(question="Qwen3.8-Max 的参数量是多少？", cited_titles=("阿里发布 Qwen3.8-Max",))
    ]
    assert db.queries == []


async def test_a_cold_transcript_falls_back_and_warms_itself(monkeypatch) -> None:
    """Postgres stays the source of truth: a flushed Redis costs one query, and
    the next turn does not pay it again."""
    cache = _Cache()
    monkeypatch.setattr(conversation, "cache_client", lambda: cache)
    db = _Db([("Kimi K3 用的是什么量化格式？", ["Kimi K3 模型概览"])])

    turns = await conversation.turns_for(db, _THREAD)

    assert [t.question for t in turns] == ["Kimi K3 用的是什么量化格式？"]
    assert len(db.queries) == 1
    assert cache.writes and cache.writes[0][0] == f"ahr:rag:v1:thread:{_THREAD}"


async def test_an_empty_thread_is_cached_rather_than_re_queried(monkeypatch) -> None:
    """`None` and `[]` are different answers. Collapsing them would send a
    five-table join after the empty result it already had — on every thread's
    first question, which is the most common case there is."""
    cache = _Cache({f"ahr:rag:v1:thread:{_THREAD}": "[]"})
    monkeypatch.setattr(conversation, "cache_client", lambda: cache)
    db = _Db([("should not be read", [])])

    assert await conversation.turns_for(db, _THREAD) == []
    assert db.queries == []


async def test_a_broken_cache_degrades_to_the_database(monkeypatch) -> None:
    """A cache that can break the feature is worse than no cache."""

    class _Broken(_Cache):
        async def get(self, key: str) -> str | None:
            raise RuntimeError("connection reset")

    monkeypatch.setattr(conversation, "cache_client", _Broken)
    db = _Db([("Kimi K3 用的是什么量化格式？", ["Kimi K3 模型概览"])])

    turns = await conversation.turns_for(db, _THREAD)
    assert [t.question for t in turns] == ["Kimi K3 用的是什么量化格式？"]


async def test_a_completed_turn_extends_the_cached_transcript(monkeypatch) -> None:
    cache = _Cache()
    monkeypatch.setattr(conversation, "cache_client", lambda: cache)

    await conversation.remember(
        _THREAD,
        [Turn(question="Qwen3.8-Max 的参数量是多少？", cited_titles=())],
        Turn(question="Qwen3.8-Max 的上下文长度是多少？", cited_titles=("阿里发布 Qwen3.8-Max",)),
    )

    written = json.loads(cache.writes[-1][1])
    assert [row["question"] for row in written] == [
        "Qwen3.8-Max 的参数量是多少？",
        "Qwen3.8-Max 的上下文长度是多少？",
    ]


async def test_the_cached_transcript_stays_bounded(monkeypatch) -> None:
    """The same bound as the database read. An unbounded cached transcript would
    quietly reintroduce the drift `MAX_TURNS` exists to prevent."""
    cache = _Cache()
    monkeypatch.setattr(conversation, "cache_client", lambda: cache)
    prior = [Turn(question=f"第 {i} 问", cited_titles=()) for i in range(20)]

    await conversation.remember(_THREAD, prior, Turn(question="最新一问", cited_titles=()))

    written = json.loads(cache.writes[-1][1])
    assert len(written) == conversation.MAX_TURNS
    assert written[-1]["question"] == "最新一问"


def test_the_cache_cannot_launder_an_answer_into_the_next_query() -> None:
    """§11 forbids treating a previous answer as a fact, and a cache is exactly
    where that rule gets quietly broken. Only the two things a rewrite may see
    are stored, so there is nothing here for a later turn to pick up."""
    source = inspect.getsource(service._extend_thread)
    assert "answer_markdown" not in source
    assert "c.title" in source

    stored = inspect.getsource(conversation._as_row)
    assert set(Turn.__dataclass_fields__) == {"question", "cited_titles"}
    assert "answer" not in stored


def test_the_cache_is_written_only_after_the_row_is_committed() -> None:
    """Database ahead of cache is the safe direction — the next read finds a
    transcript one turn short, which is a slightly worse rewrite. The reverse
    would have the cache claiming a turn that does not exist."""
    source = inspect.getsource(service.answer_question)
    assert source.index("_persist(connection, result)") < source.index(
        "await _extend_thread(result"
    )

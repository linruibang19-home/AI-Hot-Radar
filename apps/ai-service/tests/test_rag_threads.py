"""The conversation as a unit the reader can see, leave and come back to.

Multi-turn worked end to end and was invisible, which for the person using it is
indistinguishable from not existing. Three things had to be true before it was a
conversation rather than a feature that happened to be running:

* every turn reaches `rag_query` under its thread — including the ones served
  from cache, which is where this was leaking;
* a thread can be listed and reopened, so the history offers something to
  resume rather than a flat list of follow-ups detached from what they followed;
* a stored turn carries its `conversation_id` back out, so a shared answer is
  somewhere to keep asking from rather than a dead end.
"""

from __future__ import annotations

import inspect

from ahr.rag import api, service
from ahr.rag.service import load_recent_threads


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]], log: list[tuple[str, object]]) -> None:
        self.rows = rows
        self.log = log

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = ()) -> None:
        self.log.append((sql, params))

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _Connection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.log: list[tuple[str, object]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.rows, self.log)


# --- a cache hit is still a turn -------------------------------------------


def test_a_cached_answer_joins_the_thread_it_was_asked_in() -> None:
    """The defect: a follow-up served from cache returned before `_persist`, so
    it never reached `rag_query` under this conversation. It vanished on reload,
    and the *next* follow-up was rewritten against a transcript with a hole in
    it. What the cache exists to save is three provider round trips, not the row
    recording what was asked.
    """
    source = inspect.getsource(service.answer_question)
    branch = source[source.index("if cached is not None:") :]
    branch = branch[: branch.index("return cached")]

    assert "cached.conversation_id = conversation_id" in branch
    assert "_persist(connection, cached)" in branch
    assert "await _extend_thread(cached" in branch


def test_a_replayed_answer_is_shown_as_this_readers_question() -> None:
    """A semantic near-match is a *different* question — 0.97 similar, not
    identical. Replaying it under the original's wording would show the reader a
    sentence they never typed as their own, and `load_turns` reads exactly that
    field to build the next rewrite's transcript."""
    source = inspect.getsource(service.answer_question)
    branch = source[source.index("if cached is not None:") :]

    assert "cached.question = asked" in branch
    assert "replace(cached.plan, question=question)" in branch


def test_the_replayed_answers_own_permalink_stays_reachable() -> None:
    """`_persist` mints a new id, and that row owns no retrieval trace because
    no retrieval ran. The answer being replayed does own one."""
    source = inspect.getsource(service.answer_question)
    assert '"replayOf"' in source


# --- the conversation list -------------------------------------------------


ROWS = [
    (
        "2c9a1d44-5c1f-4f8e-9c3d-7a1b2c3d4e5f",
        "最近千问的动态有哪些",
        3,
        None,
    )
]


def test_a_thread_is_titled_by_the_question_that_started_it() -> None:
    """The first question is the one typed in full, before pronouns started
    standing in for it. Titling by the newest would label a conversation
    「那它的性能表现怎么样」, which says nothing about what it is about."""
    threads = load_recent_threads(_Connection(ROWS))

    assert threads[0]["title"] == "最近千问的动态有哪些"
    assert threads[0]["turns"] == 3
    assert threads[0]["conversationId"] == ROWS[0][0]


def test_the_list_groups_turns_into_conversations() -> None:
    """A flat list of turns is what a single-shot question box has. In a thread
    it reads as duplication — 「那它的性能表现怎么样」 three times, each detached from
    what it was following up on — and offers nothing to reopen."""
    connection = _Connection(ROWS)
    load_recent_threads(connection)

    sql, _ = connection.log[0]
    assert "GROUP BY conversation_id" in sql
    assert "conversation_id IS NOT NULL" in sql
    # Ordered by the most recent activity, not by when the thread started: a
    # conversation someone is still in belongs at the top.
    assert "ORDER BY max(completed_at) DESC" in sql


def test_the_list_is_bounded() -> None:
    connection = _Connection(ROWS)
    load_recent_threads(connection, 5)

    assert connection.log[0][1] == (5,)
    assert "LIMIT %s" in connection.log[0][0]


def test_reading_a_thread_list_is_not_charged_against_the_ask_quota() -> None:
    """It reads rows that were already paid for. Metering it would make the
    history unusable for anyone who had spent their twenty questions."""
    assert "_enforce_quota" not in inspect.getsource(api.threads)


# --- a stored turn can be continued ----------------------------------------


def test_a_stored_turn_carries_the_thread_it_belongs_to() -> None:
    """Without this a shared answer was a dead end: the page could render it and
    had no way to let the reader keep asking from there."""
    assert "q.conversation_id::text" in service._CONVERSATION_SELECT
    assert '"conversationId"' in inspect.getsource(service._as_conversation)


def test_one_thread_is_read_in_the_order_it_happened() -> None:
    """A transcript is the one thing where order is the content."""
    source = inspect.getsource(service.load_thread)
    assert "q.conversation_id = %s::uuid" in source
    assert "ORDER BY q.completed_at ASC" in source

"""An answer at its own address.

`rag_query` has recorded every answer since the feature shipped, and `_persist`
has always written the new id back onto the response — so the browser held an
identifier for a row that nothing could read back. The id was real and pointed
at nothing.

What is worth pinning here is mostly about *sameness*: the permalink and the
history list must reconstruct a conversation identically, because otherwise the
copy that drifts is the one strangers see.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

from ahr.rag import api
from ahr.rag.service import (
    _CONVERSATION_SELECT,
    _as_conversation,
    load_conversation,
    load_history,
)

ROW = (
    "6f1d0f3e-0b3a-4a1e-9f2c-1d2e3f4a5b6c",
    "使用 MXFP4 量化的是哪个模型？",
    "使用 MXFP4 量化的是 **Kimi K3**[1]。",
    "ANSWERED",
    {"query_type": "fact_check"},
    {"total_ms": 9700},
    datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
    ["证据只覆盖到 2026-08-06，之后是否有新版本未知。"],
    "2c9a1d44-5c1f-4f8e-9c3d-7a1b2c3d4e5f",
    [{"number": 1, "title": "Kimi K3 模型概览", "sourceName": "Hugging Face Blog"}],
)

# Where each column lands, so a future column added to `_CONVERSATION_SELECT`
# breaks the fixture at one place rather than at every index that shifted.
_CITATIONS = 9


class _Cursor:
    """Answers the conversation query with rows and the trace query with none.

    `load_conversation` makes two queries now, and a fake that returned the
    conversation row to both would hand an 8-column tuple to the trace reader,
    which expects eighteen. Keyed off the SQL so the fake stays honest about
    which question it is answering.
    """

    def __init__(self, rows: list[tuple[object, ...]], log: list[tuple[str, object]]) -> None:
        self.rows = rows
        self.log = log
        self.answering_trace = False

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = ()) -> None:
        self.log.append((sql, params))
        self.answering_trace = "rag_trace" in sql

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return [] if self.answering_trace else self.rows


class _Connection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.log: list[tuple[str, object]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.rows, self.log)


# --- the two readers agree -------------------------------------------------


def test_a_permalink_and_the_history_list_build_the_same_conversation() -> None:
    """The property that matters. Two hand-written projections of the same rows
    would let the shared link and the in-page list disagree about an answer."""
    single = load_conversation(_Connection([ROW]), ROW[0])
    listed = load_history(_Connection([ROW]))
    assert single is not None

    # The permalink carries one extra field, and only the permalink: the
    # history list renders twenty conversations and would pull forty candidate
    # rows for each to show something none of them displays.
    assert "trace" in single
    assert "trace" not in listed[0]
    assert {k: v for k, v in single.items() if k != "trace"} == listed[0]


def test_both_readers_use_one_select() -> None:
    for reader in (load_conversation, load_history):
        assert "_CONVERSATION_SELECT" in inspect.getsource(reader)


def test_the_shape_is_what_the_client_already_renders() -> None:
    conversation = _as_conversation(ROW)

    assert conversation["queryId"] == ROW[0]
    assert conversation["question"] == ROW[1]
    assert conversation["refused"] is False
    assert conversation["citations"] == ROW[_CITATIONS]
    assert conversation["askedAt"] == "2026-08-06T12:00:00+00:00"
    # The thread this turn belongs to. Without it a shared answer was a dead
    # end: the page could render it and had nothing to keep asking from.
    assert conversation["conversationId"] == ROW[8]


def test_a_rewritten_follow_up_is_derived_rather_than_stored() -> None:
    """`retrieval_plan.question` has recorded the *issued* question since the
    planner shipped, so what a follow-up was understood as needs no column of
    its own — it is that field differing from the one the reader typed."""
    assert _as_conversation(ROW)["rewrittenQuestion"] is None

    followup = (
        *ROW[:1],
        "那它的参数量呢？",
        *ROW[2:4],
        {"query_type": "fact_check", "question": "Kimi K3 的参数量是多少？"},
        *ROW[5:],
    )
    assert _as_conversation(followup)["rewrittenQuestion"] == "Kimi K3 的参数量是多少？"


def test_the_answers_own_caveats_survive_the_round_trip() -> None:
    """V015. These were hard-coded to `[]` while the live endpoint returned
    them, so the permalink — the copy that gets shared and quoted — showed the
    answer with its qualifications removed. The stored copy must not be more
    confident than the one that was generated."""
    assert _as_conversation(ROW)["limitations"] == ROW[7]


def test_a_refusal_replays_as_a_refusal() -> None:
    """A stored refusal must not come back looking like an empty answer: the
    locked constraint is that "there is not enough evidence" is an outcome, and
    a permalink that dropped it would be showing something that never happened."""
    row = (*ROW[:2], "", "REFUSED", *ROW[4:])
    conversation = _as_conversation(row)

    assert conversation["refused"] is True
    assert conversation["refusalReason"]


# --- lookup ----------------------------------------------------------------


def test_a_missing_conversation_is_absent_not_an_error() -> None:
    assert load_conversation(_Connection([]), str(uuid.uuid4())) is None


def test_a_malformed_id_is_absent_rather_than_a_crash() -> None:
    """The id is a path segment, so it is user input. Handing "abc" to psycopg
    as a uuid raises, and a 500 on a mistyped URL is a bug, not a 404."""
    for bad in ("abc", "", "../etc/passwd", "1; DROP TABLE rag_query"):
        assert load_conversation(_Connection([ROW]), bad) is None


def test_the_id_is_bound_as_a_parameter() -> None:
    connection = _Connection([ROW])
    load_conversation(connection, ROW[0])

    sql, params = connection.log[0]
    assert "WHERE q.id = %s" in sql
    assert params == (uuid.UUID(ROW[0]),)
    # The trace is a second query against the same id, not a join: joining it
    # into the conversation select would multiply the citation aggregate by the
    # number of traced candidates.
    assert any("rag_trace" in sql for sql, _ in connection.log[1:])


def test_the_select_is_shared_verbatim() -> None:
    connection = _Connection([ROW])
    load_conversation(connection, ROW[0])
    assert connection.log[0][0].startswith(_CONVERSATION_SELECT)


# --- the endpoint ----------------------------------------------------------


def test_replaying_an_answer_is_not_charged_against_the_ask_quota() -> None:
    """The quota bounds spend on embedding, reranking and generation. A
    permalink does none of those — it reads a row that was already paid for —
    and metering it would make a shared link fail for the person it was shared
    with, on their first visit."""
    source = inspect.getsource(api.conversation)
    assert "_enforce_quota" not in source

    # The endpoints that do cost money still charge for it.
    for endpoint in (api.ask, api.ask_stream):
        assert "_enforce_quota" in inspect.getsource(endpoint)


def test_an_unknown_conversation_is_a_404() -> None:
    source = inspect.getsource(api.conversation)
    assert "status_code=404" in source

"""HTTP surface for question answering.

`POST /rag/ask` answers in one response; `POST /rag/ask/stream` reports progress
over SSE (`AHR-API-500` §4) and delivers the finished answer as its last event.

The stream carries three kinds of event: `stage` for progress, `delta` for the
answer as it is written, and one final `answer` holding the verified result.

**Raw model tokens are still never relayed.** §4 requires the server to resolve
citations before delivery, so what `delta` carries has already been through the
same rules `bind_citations` applies to the finished string: invented `[n]`
markers are deleted, real ones carry their final reading-order number, and
nothing is sent at all until the answer is guaranteed not to become a refusal.
`incremental.py` explains why that guarantee is reachable mid-stream — briefly,
renumbering is left-to-right and the evidence set is known before generation
starts, so only the "no citations means refusal" invariant needs the end of the
text, and holding until the first resolved citation settles it.

This note used to say token streaming needed the model to emit its claims before
its prose. That turned out not to be true, and the belief was never tested: the
binding was already incremental, and the actual blocker was one invariant.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ahr.processing.llm import LlmUnavailableError
from ahr.processing.llm import build_client_from_env as build_llm
from ahr.rag.answer import Answer
from ahr.rag.embeddings import EmbeddingUnavailableError
from ahr.rag.embeddings import build_client_from_env as build_embedder
from ahr.rag.ratelimit import caller_id, check, get_client
from ahr.rag.rerank import RerankUnavailableError
from ahr.rag.rerank import build_client_from_env as build_reranker
from ahr.rag.service import answer_question

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])

MAX_QUESTION_CHARS = 300

# Collapse concurrent cold requests for the same dashboard window.  The lock
# is process-local by design: Redis is not a distributed lock or source of
# truth here, and a future multi-worker deployment may harmlessly compute one
# snapshot per worker after a cache flush.
_stats_locks: dict[int, asyncio.Lock] = {}


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=MAX_QUESTION_CHARS)
    # The reader correcting the resolved range. Optional and absent by default:
    # the planner's own resolution is right for almost every question, and this
    # exists for the case where it is not — which the page previously displayed
    # and gave no way to act on.
    timeFrom: date | None = None
    timeTo: date | None = None
    # The thread this question continues. Absent on the first turn; the server
    # mints one and returns it, so the client never has to invent an id that
    # must then be trusted.
    conversationId: str | None = None

    def window(self) -> tuple[date, date] | None:
        if self.timeFrom is None or self.timeTo is None:
            return None
        if self.timeTo < self.timeFrom:
            raise HTTPException(status_code=422, detail="结束日期早于开始日期")
        return (self.timeFrom, self.timeTo)


def _bypass_cache(http: Request) -> bool:
    """Honour `Cache-Control: no-cache` on the ask endpoints.

    Not a test hook: an operator looking at a suspect answer needs to re-run it
    against the live pipeline, and "ask again" is useless when the same cached
    row comes back. The standard header already means exactly this, so it does
    not need a bespoke query parameter.

    It only skips *reading* the cache. The fresh answer is still stored, so a
    diagnostic request also refreshes the entry rather than leaving the
    suspect one in place.
    """
    directive = (http.headers.get("cache-control") or "").lower()
    return "no-cache" in directive or "no-store" in directive


def _enforce_spend() -> None:
    """Stop before the call when today's ceiling is reached.

    Separate from the per-caller quota because it answers a different question.
    The quota bounds one visitor; this bounds the deployment — twenty visitors
    each inside their allowance reach the same bill, and the quota fails open on
    a Redis restart, so it should not be the only thing between a public
    endpoint and a provider account.
    """
    import psycopg

    from ahr.config import get_settings
    from ahr.spend import check

    with psycopg.connect(get_settings().database_url) as connection:
        decision = check(connection)

    if not decision.allowed:
        logger.warning("daily token ceiling reached: %d/%d", decision.used, decision.limit)
        raise HTTPException(status_code=503, detail=decision.message)


async def _enforce_quota(http: Request) -> None:
    """Charge this call against the anonymous quota, or refuse it.

    Applied to both endpoints. Answering costs an embedding, a rerank and a
    generation, so an unguarded public `/ask` spends real money for anyone who
    walks it.
    """
    caller = caller_id(
        http.headers.get("x-forwarded-for"), http.client.host if http.client else None
    )
    decision = await check(get_client(), caller)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=decision.message,
            headers={"Retry-After": str(decision.retry_after)},
        )


def _conversation_id(request: AskRequest) -> str:
    """The thread this question belongs to, minted here when it is the first.

    Server-side rather than client-side because the id keys stored rows: a
    client free to choose it could read another reader's thread by guessing,
    and there are no accounts yet to scope that by.

    A malformed id is treated as a new thread rather than rejected — a follow-up
    that starts a fresh conversation is a mildly worse answer, and a 422 in its
    place is no answer at all.
    """
    raw = (request.conversationId or "").strip()
    if raw:
        try:
            return str(uuid.UUID(raw))
        except ValueError:
            logger.warning("ignoring malformed conversation id")
    return str(uuid.uuid4())


@router.post("/ask")
async def ask(request: AskRequest, http: Request) -> dict[str, object]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be blank")

    await _enforce_quota(http)
    _enforce_spend()
    answer = await _answer(
        question,
        bypass_cache=_bypass_cache(http),
        window_override=request.window(),
        conversation_id=_conversation_id(request),
    )
    return answer.as_dict()


@router.get("/suggestions/{query_id}")
async def suggestions(query_id: str) -> dict[str, object]:
    """Follow-ups this answer's own sources could support.

    A separate request on purpose: the answer is already ~10s of external round
    trips, and folding a fourth into it would make the reader wait longer for
    something they have not asked for. Fetched after the answer renders, and
    silent when it fails — no chips is a fine outcome, an error toast is not.

    Cached by query id: an answer's suggestions cannot change while the answer
    does not.
    """
    import psycopg

    from ahr.config import get_settings
    from ahr.rag.cache import client as cache_client
    from ahr.rag.suggest import suggest

    key = f"ahr:rag:suggest:{query_id}"
    client = cache_client()
    try:
        cached = await client.get(key)
        if cached:
            return {"suggestions": json.loads(cached)}
    except Exception as exc:  # noqa: BLE001 - a cache must never break a feature
        logger.warning("suggestion cache read failed: %s", exc)

    try:
        llm = build_llm()
    except LlmUnavailableError:
        return {"suggestions": []}

    async with llm:
        with psycopg.connect(get_settings().database_url) as connection:
            rows = await suggest(connection, llm, query_id)

    try:
        await client.set(key, json.dumps(rows, ensure_ascii=False), ex=86_400)
    except Exception as exc:  # noqa: BLE001
        logger.warning("suggestion cache write failed: %s", exc)

    return {"suggestions": rows}


@router.get("/conversations/{conversation_id}")
def conversation_turns(conversation_id: str) -> dict[str, object]:
    """One thread, oldest first — what a reload needs to restore.

    `/history` returns the site's recent questions across every thread, which is
    a different question and was the only one answered. So refreshing the page
    mid-conversation dropped it and showed the reader strangers' questions
    instead of their own.
    """
    import psycopg

    from ahr.config import get_settings
    from ahr.rag.service import load_thread

    try:
        uuid.UUID(conversation_id)
    except ValueError:
        # A malformed id is an empty thread, not an error: the page renders a
        # fresh conversation, which is what the reader gets anyway.
        return {"turns": []}

    with psycopg.connect(get_settings().database_url) as connection:
        return {"turns": load_thread(connection, conversation_id)}


@router.get("/threads")
def threads(limit: int = 20) -> dict[str, object]:
    """Recent conversations, one row each, newest first.

    What a chat surface's history list needs. `/history` returns individual
    turns, which in a threaded page shows the same follow-up three times with
    nothing saying what each was following up on — and gives the reader nothing
    to resume, because the resumable unit is the thread.

    Still the site's conversations rather than a reader's: there are no accounts
    until M5, and the page says so.
    """
    import psycopg

    from ahr.config import get_settings
    from ahr.rag.service import THREAD_LIMIT, load_recent_threads

    with psycopg.connect(get_settings().database_url) as connection:
        return {"threads": load_recent_threads(connection, min(limit, THREAD_LIMIT))}


@router.get("/history")
def history(limit: int = 20) -> dict[str, object]:
    """Recent conversations, newest first.

    No accounts until M5, so this is the site's history rather than a reader's.
    The page says so; a shared list presented as personal would be worse than
    no list.
    """
    import psycopg

    from ahr.config import get_settings
    from ahr.rag.service import HISTORY_LIMIT, load_history

    with psycopg.connect(get_settings().database_url) as connection:
        return {"conversations": load_history(connection, min(limit, HISTORY_LIMIT))}


@router.get("/stats")
async def stats(days: int = 30) -> dict[str, object]:
    """Cost, latency and corpus scale, from rows the system already writes.

    Read-only and unmetered, like the permalink: it aggregates records rather
    than producing anything.
    """
    import psycopg

    from ahr.config import get_settings
    from ahr.rag.cache import client as cache_client
    from ahr.rag.cache import get_ops_stats, put_ops_stats
    from ahr.rag.cache import stats as cache_stats
    from ahr.rag.ops import (
        corpus_summary,
        cost_summary,
        latency_summary,
        retrieval_summary,
    )

    window = max(1, min(days, 365))
    redis_client = cache_client()
    cached = await get_ops_stats(redis_client, window)
    if cached is not None:
        return cached

    lock = _stats_locks.setdefault(window, asyncio.Lock())
    async with lock:
        # Another request may have filled Redis while this request waited.
        cached = await get_ops_stats(redis_client, window)
        if cached is not None:
            return cached

        def aggregate() -> dict[str, object]:
            # psycopg is synchronous.  Running it in the event loop made twenty
            # dashboard readers serialize every query and created a four-second
            # p99 despite each SQL statement being fast in EXPLAIN ANALYZE.
            with psycopg.connect(get_settings().database_url) as connection:
                return {
                    "cost": cost_summary(connection, days=window),
                    "latency": latency_summary(connection, days=window),
                    # What retrieval did on real questions, which the 90-question
                    # golden set cannot report: this is real traffic population.
                    "retrieval": retrieval_summary(connection, days=window),
                    "corpus": corpus_summary(connection),
                }

        snapshot = await asyncio.to_thread(aggregate)
        # Cache counters live in Redis and are cheap.  They are attached after
        # the PostgreSQL work so a Redis outage cannot block the database read.
        snapshot["cache"] = await cache_stats(redis_client)
        await put_ops_stats(redis_client, window, snapshot)
        return snapshot


@router.get("/query/{query_id}")
def conversation(query_id: str) -> dict[str, object]:
    """One answer, addressable by id.

    Read-only and unmetered: it replays a row that was already paid for. Putting
    it behind the ask quota would make a shared link fail for the person it was
    shared with, which is the one thing a permalink must not do.
    """
    import psycopg

    from ahr.config import get_settings
    from ahr.rag.service import load_conversation

    with psycopg.connect(get_settings().database_url) as connection:
        found: dict[str, object] | None = load_conversation(connection, query_id)

    if found is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return found


def _clients() -> tuple[Any, Any, Any]:
    """Build the three providers, or raise the right 503."""
    try:
        embedder = build_embedder()
    except EmbeddingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"embedding unavailable: {exc}") from exc

    # A missing reranker degrades ranking quality; it must not take the feature
    # down. `retrieve` records the degradation in the response metrics.
    reranker = None
    try:
        reranker = build_reranker()
    except RerankUnavailableError as exc:
        logger.warning("reranker not configured: %s", exc)

    try:
        llm = build_llm()
    except LlmUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"llm unavailable: {exc}") from exc

    return embedder, reranker, llm


async def _answer(
    question: str,
    on_stage: Any = None,
    on_delta: Any = None,
    *,
    bypass_cache: bool = False,
    window_override: tuple[date, date] | None = None,
    conversation_id: str | None = None,
) -> Answer:
    embedder, reranker, llm = _clients()
    async with embedder, llm:
        if reranker is not None:
            async with reranker:
                return await answer_question(
                    question,
                    embedder=embedder,
                    reranker=reranker,
                    llm=llm,
                    asked_at=datetime.now(UTC),
                    on_stage=on_stage,
                    on_delta=on_delta,
                    bypass_cache=bypass_cache,
                    window_override=window_override,
                    conversation_id=conversation_id,
                )
        return await answer_question(
            question,
            embedder=embedder,
            reranker=None,
            llm=llm,
            asked_at=datetime.now(UTC),
            on_stage=on_stage,
            on_delta=on_delta,
            bypass_cache=bypass_cache,
            window_override=window_override,
            conversation_id=conversation_id,
        )


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/ask/stream")
async def ask_stream(request: AskRequest, http: Request) -> StreamingResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be blank")

    # Before the stream opens, so a refusal is a 429 the client can read rather
    # than a 200 whose first event says it was rejected.
    await _enforce_quota(http)
    _enforce_spend()

    # Provider failures are raised before the response starts, so a missing key
    # is still a 503 rather than a 200 whose first event says it failed.
    _clients()
    bypass = _bypass_cache(http)
    window = request.window()
    conversation = _conversation_id(request)

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def on_stage(name: str, detail: dict[str, Any]) -> None:
            await queue.put(("stage", {"stage": name, **detail}))

        async def on_delta(text: str) -> None:
            await queue.put(("delta", {"text": text}))

        async def run() -> None:
            try:
                answer = await _answer(
                    question,
                    on_stage=on_stage,
                    on_delta=on_delta,
                    bypass_cache=bypass,
                    window_override=window,
                    conversation_id=conversation,
                )
                await queue.put(("answer", answer.as_dict()))
            except Exception as exc:  # noqa: BLE001 - the stream must report, not 500
                logger.exception("streamed answer failed")
                await queue.put(("error", {"error": str(exc)}))
            finally:
                # Sentinel rather than racing the task against the queue: the
                # producer decides when there is nothing more to send.
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                name, payload = item
                yield _sse(name, payload)
        finally:
            # A reader who navigates away mid-query must not leave the pipeline
            # running against a socket nobody is reading.
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx buffers text/event-stream by default, which would hold every
            # progress event until the answer arrived and defeat the point.
            "X-Accel-Buffering": "no",
        },
    )

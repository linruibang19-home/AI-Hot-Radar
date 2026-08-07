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
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=MAX_QUESTION_CHARS)


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


@router.post("/ask")
async def ask(request: AskRequest, http: Request) -> dict[str, object]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be blank")

    await _enforce_quota(http)
    answer = await _answer(question, bypass_cache=_bypass_cache(http))
    return answer.as_dict()


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
    from ahr.rag.cache import stats as cache_stats
    from ahr.rag.ops import corpus_summary, cost_summary, latency_summary

    window = max(1, min(days, 365))
    with psycopg.connect(get_settings().database_url) as connection:
        return {
            "cost": cost_summary(connection, days=window),
            "latency": latency_summary(connection, days=window),
            "corpus": corpus_summary(connection),
            # A cache nobody can measure is a cache nobody should trust.
            "cache": await cache_stats(cache_client()),
        }


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
        found = load_conversation(connection, query_id)

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

    # Provider failures are raised before the response starts, so a missing key
    # is still a 503 rather than a 200 whose first event says it failed.
    _clients()
    bypass = _bypass_cache(http)

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def on_stage(name: str, detail: dict[str, Any]) -> None:
            await queue.put(("stage", {"stage": name, **detail}))

        async def on_delta(text: str) -> None:
            await queue.put(("delta", {"text": text}))

        async def run() -> None:
            try:
                answer = await _answer(
                    question, on_stage=on_stage, on_delta=on_delta, bypass_cache=bypass
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

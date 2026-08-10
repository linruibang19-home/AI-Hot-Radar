"""Caching for question answering (T3-6, ADR-0017).

The latency run settled where the time goes: **99% of a query is three external
round trips** — embed 18%, rerank 28%, generate 53% — and local retrieval,
fusion and parent expansion together cost under 1%. Nothing in the RAG path was
cached, so asking the same question twice paid the full bill twice.

Three layers, each with a different staleness risk and therefore a different
rule:

1. **Embedding cache** (exact key on model + question). A pure function of its
   inputs, so there is no staleness to reason about: the same text and the same
   model give the same vector forever. Long TTL.

2. **Answer cache** (exact key on the canonical question + prompt version +
   **corpus fingerprint**). This is the freshness-aware part. An answer about a
   news corpus is only valid for the corpus it was drawn from — "本周 DeepSeek
   有什么动态" answered yesterday is *wrong* today, not merely stale — so the
   fingerprint goes into the key and new content invalidates every entry by
   construction rather than by a TTL that hopes to be short enough.

3. **Semantic near-match**. The same idea a step looser: reuse an answer whose
   *question* is near-identical in embedding space. This is the layer that
   requires the most caution, and the caution is the interesting part —

   * the threshold is **0.97**, not the 0.85 a demo would use. "DeepSeek 发布了
     什么" and "OpenAI 发布了什么" are far closer than intuition suggests, and a
     loose threshold does not return a slightly-worse answer, it returns a
     confident answer about the wrong company;
   * a near-match must share the **same corpus fingerprint**, so it can never
     outlive the content it was built from;
   * it rides on the embedding computed for this query anyway, so a miss costs
     one dot product per cached entry and no API call.

**Refusals are never cached.** A refusal means *the corpus did not contain the
answer yet*, which is the single most time-dependent statement the system makes;
caching it would keep saying "no" after the answer arrived.

No new infrastructure: Redis is already a dependency and ADR-005 already scopes
it to cache, rate limiting and short locks. Nothing here is a source of truth —
a flushed Redis costs latency and money, never correctness.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import re
import struct
from collections.abc import Awaitable
from typing import Any, TypeVar, cast

import redis.asyncio as redis

from ahr.rag.planner import DISPLAY_TIMEZONE

logger = logging.getLogger(__name__)

# redis-py types several commands as `Awaitable[T] | T` so one set of stubs can
# serve both the sync and async clients. On the async client they are always
# awaitable; the cast says so without loosening anything else.
_T = TypeVar("_T")


def _awaited(value: Awaitable[_T] | _T) -> Awaitable[_T]:
    return cast("Awaitable[_T]", value)


# Bump to invalidate every entry at once after a change to what is stored.
CACHE_VERSION = "v1"

EMBEDDING_TTL = 7 * 86_400
ANSWER_TTL = 3_600

# Deliberately high. See the module docstring: a loose threshold on this corpus
# does not degrade an answer, it answers a different question.
SEMANTIC_THRESHOLD = 0.97

# How many recent questions the near-match index holds. Bounded because the
# lookup is a linear scan, and because an unbounded index is an unbounded way to
# serve an old answer.
SEMANTIC_INDEX_SIZE = 200

_ANSWER_PREFIX = f"ahr:rag:{CACHE_VERSION}:answer"
_EMBED_PREFIX = f"ahr:rag:{CACHE_VERSION}:embed"
_SEMANTIC_INDEX = f"ahr:rag:{CACHE_VERSION}:semindex"
_COUNTER = f"ahr:rag:{CACHE_VERSION}:hits"

_WHITESPACE = re.compile(r"\s+")

_client: redis.Redis | None = None


def client() -> redis.Redis:
    """One connection pool for the process, as the rate limiter does.

    Separate from `ratelimit`'s client only because the two have unrelated
    lifecycles; both talk to the same Redis.
    """
    global _client
    if _client is None:
        from ahr.config import get_settings

        _client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def canonical(question: str) -> str:
    """Normalise the form of a question without touching its meaning.

    Case folding and whitespace collapsing only. Deliberately not stemming or
    stop-word removal: "DeepSeek V3 和 V4 的区别" and "DeepSeek V4 和 V3 的区别"
    must stay distinct keys, and aggressive normalisation is how an exact cache
    quietly becomes a fuzzy one.
    """
    return _WHITESPACE.sub(" ", question.strip()).casefold()


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


def corpus_fingerprint(connection: Any, *, freshness_required: bool) -> str:
    """A value that changes when an answer to *this kind of question* would.

    Counting *embedded* chunks rather than items: an item that exists but has
    not been chunked and embedded cannot be retrieved, so it cannot change an
    answer, and letting it invalidate the cache would throw entries away for
    nothing.

    **Two granularities, chosen by the planner's `freshness_required`.** The
    first version used the exact corpus state for everything, which is provably
    correct and turned out to be useless: ingestion polls every 120 seconds, so
    a question repeated a minute later already saw a different fingerprint and
    missed. Measured — two identical questions, `92e5b821` then `b8518432`.

    The distinction the planner already draws is exactly the one that matters:

    * `freshness_required` (最新动态 / 时间线) — bound to the exact corpus. These
      are the questions where a stale answer is *wrong* rather than merely old,
      so they should miss whenever anything arrived. That is the intended cost.
    * everything else (原理解释 / 事实核查 / 对比) — bound to the day. "Kimi K3
      用的是什么量化格式" does not change because three unrelated articles were
      published; pinning it to the exact corpus was buying invalidation that
      protected against nothing, and the TTL still caps how old it can get.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT (SELECT count(*) FROM content_chunk WHERE embedding IS NOT NULL),
                   (SELECT max(COALESCE(published_at, observed_at)) FROM content_item)
            """
        )
        row = cursor.fetchone() or (0, None)

    if freshness_required:
        return _digest("exact", str(row[0]), str(row[1]))

    newest = row[1]
    day = newest.astimezone(DISPLAY_TIMEZONE).date().isoformat() if newest else "empty"
    return _digest("daily", day)


# --- embeddings -------------------------------------------------------------


def _pack(vector: list[float]) -> str:
    return base64.b64encode(struct.pack(f"{len(vector)}f", *vector)).decode("ascii")


def _unpack(blob: str) -> list[float]:
    raw = base64.b64decode(blob)
    return list(struct.unpack(f"{len(raw) // 4}f", raw))


async def get_embedding(client: redis.Redis, model: str, question: str) -> list[float] | None:
    key = f"{_EMBED_PREFIX}:{_digest(model, canonical(question))}"
    try:
        blob = await client.get(key)
    except Exception as exc:  # noqa: BLE001 - a cache must never break the feature
        logger.warning("embedding cache read failed: %s", exc)
        return None
    return _unpack(blob) if blob else None


async def put_embedding(
    client: redis.Redis, model: str, question: str, vector: list[float]
) -> None:
    key = f"{_EMBED_PREFIX}:{_digest(model, canonical(question))}"
    try:
        await client.set(key, _pack(vector), ex=EMBEDDING_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding cache write failed: %s", exc)


# --- answers ----------------------------------------------------------------


# Bumped when the answer *post-processing* changes, independently of the prompt.
#
# `prompt_version` covers what the model was asked; it says nothing about what
# the server does to the reply afterwards. Support gating (2026-08-09) removes
# citations the cross-encoder scores below threshold — so an entry written
# before it shipped serves exactly the citation the gate exists to withhold,
# for up to ANSWER_TTL after deploy. The prompt did not change, so bumping
# `ANSWER_PROMPT_VERSION` would have been a lie about the cause.
#
# Separate from `CACHE_VERSION` on purpose: that one also namespaces the
# embedding cache, whose 7-day entries are still perfectly valid here and cost
# a provider round trip each to rebuild.
ANSWER_PIPELINE_VERSION = "gated-1"


def answer_key(
    question: str, *, fingerprint: str, prompt_version: str, window: str | None = None
) -> str:
    """Key an answer by everything that can change it.

    `window` carries a reader-supplied time range. The same words over two
    different ranges are two different questions, and keying on the words alone
    would hand one reader the other's window — the same shape as serving a
    pre-gating answer after the gate shipped.
    """
    digest = _digest(
        canonical(question),
        fingerprint,
        prompt_version,
        ANSWER_PIPELINE_VERSION,
        window or "",
    )
    return f"{_ANSWER_PREFIX}:{digest}"


async def get_answer(client: redis.Redis, key: str) -> dict[str, Any] | None:
    try:
        blob = await client.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("answer cache read failed: %s", exc)
        return None
    if not blob:
        return None
    try:
        payload: dict[str, Any] = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return payload


async def put_answer(client: redis.Redis, key: str, payload: dict[str, Any]) -> None:
    """Store an answer. Refusals are rejected here rather than at every call site.

    A refusal says the corpus did not contain the answer *yet*. It is the most
    time-dependent thing this system ever says, and caching it would keep
    saying no after the answer arrived.
    """
    if payload.get("refused"):
        return
    try:
        await client.set(key, json.dumps(payload, ensure_ascii=False), ex=ANSWER_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("answer cache write failed: %s", exc)


# --- conversation transcripts -----------------------------------------------

# How long a thread stays warm. Deliberately close to one sitting: the browser
# keeps its thread id in `sessionStorage` for the same reason, and a transcript
# that outlived the tab holding it would only ever be read after the reader had
# forgotten what it said.
TRANSCRIPT_TTL = 2 * 3_600

_TRANSCRIPT_PREFIX = f"ahr:rag:{CACHE_VERSION}:thread"


def transcript_key(conversation_id: str) -> str:
    return f"{_TRANSCRIPT_PREFIX}:{conversation_id}"


async def get_transcript(client: redis.Redis, conversation_id: str) -> list[dict[str, Any]] | None:
    """This thread's recent turns, or None when nothing is cached.

    **None and `[]` are different answers and the caller depends on it.** None
    means "not cached, go and read the database"; `[]` means "cached, and this
    thread genuinely has no earlier turns" — which is every thread's first
    question, the most common case there is. Collapsing the two would send a
    five-table join after the empty result it already had.
    """
    try:
        blob = await client.get(transcript_key(conversation_id))
    except Exception as exc:  # noqa: BLE001 - a cache must never break the feature
        logger.warning("transcript cache read failed: %s", exc)
        return None
    if blob is None:
        return None
    try:
        loaded = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, list) else None


async def put_transcript(
    client: redis.Redis, conversation_id: str, turns: list[dict[str, Any]]
) -> None:
    """Replace this thread's cached transcript.

    Written whole rather than appended to. The turns are already in memory at
    every call site — the service has just loaded them to rewrite the follow-up
    — so a read-modify-write would be re-reading something it is holding, and a
    list append would leave the two representations able to disagree about
    ordering after a partial failure.
    """
    try:
        await client.set(
            transcript_key(conversation_id),
            json.dumps(turns, ensure_ascii=False),
            ex=TRANSCRIPT_TTL,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("transcript cache write failed: %s", exc)


# --- semantic near-match ----------------------------------------------------


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


async def semantic_lookup(
    client: redis.Redis,
    vector: list[float],
    *,
    fingerprint: str,
    threshold: float = SEMANTIC_THRESHOLD,
) -> tuple[str, float] | None:
    """The cache key of a near-identical question, if one exists.

    Entries from a different corpus fingerprint are skipped rather than scored:
    a question can be identical and still deserve a different answer once the
    corpus has moved.
    """
    try:
        entries = await _awaited(client.lrange(_SEMANTIC_INDEX, 0, SEMANTIC_INDEX_SIZE - 1))
    except Exception as exc:  # noqa: BLE001
        logger.warning("semantic index read failed: %s", exc)
        return None

    best: tuple[str, float] | None = None
    for entry in entries:
        try:
            record = json.loads(entry)
        except json.JSONDecodeError:
            continue
        if record.get("fingerprint") != fingerprint:
            continue
        score = cosine(vector, _unpack(record["vector"]))
        if score >= threshold and (best is None or score > best[1]):
            best = (record["key"], score)
    return best


async def semantic_remember(
    client: redis.Redis, vector: list[float], *, key: str, fingerprint: str
) -> None:
    entry = json.dumps({"key": key, "fingerprint": fingerprint, "vector": _pack(vector)})
    try:
        async with client.pipeline(transaction=True) as pipe:
            pipe.lpush(_SEMANTIC_INDEX, entry)
            pipe.ltrim(_SEMANTIC_INDEX, 0, SEMANTIC_INDEX_SIZE - 1)
            await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("semantic index write failed: %s", exc)


# --- observability ----------------------------------------------------------


async def record(client: redis.Redis, outcome: str) -> None:
    """Count hits and misses so the cache can be judged rather than assumed."""
    try:
        await _awaited(client.hincrby(_COUNTER, outcome, 1))
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache counter failed: %s", exc)


async def stats(client: redis.Redis) -> dict[str, Any]:
    try:
        counters = await _awaited(client.hgetall(_COUNTER))
        indexed = await _awaited(client.llen(_SEMANTIC_INDEX))
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache stats failed: %s", exc)
        return {}

    counts = {name: int(value) for name, value in (counters or {}).items()}
    answered = sum(counts.get(name, 0) for name in ("miss", "exact", "semantic"))
    return {
        "counts": counts,
        "indexed": int(indexed or 0),
        "threshold": SEMANTIC_THRESHOLD,
        "answerTtlSeconds": ANSWER_TTL,
        "hitRate": (
            round((counts.get("exact", 0) + counts.get("semantic", 0)) / answered, 4)
            if answered
            else 0.0
        ),
        "embeddingHitRate": (
            round(
                counts.get("embed_hit", 0)
                / (counts.get("embed_hit", 0) + counts.get("embed_miss", 0)),
                4,
            )
            if (counts.get("embed_hit", 0) + counts.get("embed_miss", 0))
            else 0.0
        ),
    }

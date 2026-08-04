"""Anonymous rate limiting for question answering (`AHR-API-500` §4).

The spec has required this since M4 and it was never implemented, which was
survivable while the only caller was a browser on localhost. It stops being
survivable the moment `/ask` is reachable from the internet: every call costs an
embedding, a rerank and a generation, so a single crawler walking the endpoint
spends real money until the provider quota is gone.

Redis rather than in-process counters, for one reason that matters here: there
are three Python containers sharing one deployment, and a per-process counter
would grant each of them the full allowance. Redis is already a dependency.

Fails **open**. A limiter that takes the feature down when Redis restarts trades
a bounded cost problem for an outage, and the quotas exist to bound spend, not
to be a security control — there is no authentication to protect yet.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import redis.asyncio as redis

from ahr.config import get_settings

logger = logging.getLogger(__name__)

# §4: anonymous callers get 3 per minute and 20 per day.
PER_MINUTE = 3
PER_DAY = 20

_MINUTE = 60
_DAY = 86_400


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0
    scope: str = ""

    @property
    def message(self) -> str:
        if self.scope == "day":
            return "今日提问次数已用完，请明天再来。"
        return "提问过于频繁，请稍后再试。"


def _keys(caller: str, now: float) -> tuple[tuple[str, int, int], ...]:
    """Fixed windows keyed by the window index.

    A fixed window lets a caller spend two windows' worth across a boundary.
    That is accepted deliberately: the alternative — a sliding log — stores one
    entry per request, and the quantity being defended here is a monthly bill,
    not a login form.
    """
    minute = int(now // _MINUTE)
    day = int(now // _DAY)
    return (
        (f"ahr:rl:{caller}:m:{minute}", PER_MINUTE, _MINUTE),
        (f"ahr:rl:{caller}:d:{day}", PER_DAY, _DAY),
    )


async def check(client: redis.Redis, caller: str, *, now: float | None = None) -> Decision:
    """Count this call against both windows, and say whether it may proceed."""
    moment = now if now is not None else time.time()

    for key, limit, ttl in _keys(caller, moment):
        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                # Set the expiry every time rather than only on creation: a key
                # that somehow lost its TTL would otherwise bar the caller for
                # good.
                pipe.expire(key, ttl)
                used, _ = await pipe.execute()
        except Exception as exc:  # noqa: BLE001 - see module docstring
            logger.warning("rate limit check failed, allowing: %s", exc)
            return Decision(allowed=True)

        if int(used) > limit:
            scope = "day" if ttl == _DAY else "minute"
            return Decision(allowed=False, retry_after=ttl, scope=scope)

    return Decision(allowed=True)


def caller_id(forwarded_for: str | None, client_host: str | None) -> str:
    """Identify the caller behind a proxy.

    The deployment puts Cloudflare and Caddy in front, so `request.client.host`
    is the proxy on every request and would put the whole internet in one
    bucket. The **first** entry of `X-Forwarded-For` is the original client;
    later entries are the proxies it passed through.

    Spoofable, and that is fine — see the module docstring on what this defends.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return client_host or "unknown"


_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client

"""Anonymous quotas on question answering (AHR-API-500 §4).

Required by the spec since M4 and never implemented. Harmless while the only
caller was a browser on localhost; the moment `/ask` is public, every call costs
an embedding, a rerank and a generation, and one crawler walking the endpoint
drains the provider quota.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ahr.rag.ratelimit import PER_DAY, PER_MINUTE, caller_id, check


class _Pipeline:
    """Enough of redis-py's pipeline to count."""

    def __init__(self, store: dict[str, int], fail: bool = False) -> None:
        self.store = store
        self.fail = fail
        self.key: str | None = None

    async def __aenter__(self) -> _Pipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def incr(self, key: str) -> None:
        self.key = key

    def expire(self, key: str, ttl: int) -> None:
        return None

    async def execute(self) -> list[Any]:
        if self.fail:
            raise ConnectionError("redis is down")
        assert self.key is not None
        self.store[self.key] = self.store.get(self.key, 0) + 1
        return [self.store[self.key], True]


class _Redis:
    def __init__(self, fail: bool = False) -> None:
        self.store: dict[str, int] = {}
        self.fail = fail

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self.store, self.fail)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# --- the quotas ------------------------------------------------------------


def test_calls_within_the_minute_quota_are_allowed() -> None:
    client = _Redis()
    for _ in range(PER_MINUTE):
        assert _run(check(client, "1.2.3.4", now=1000.0)).allowed


def test_the_call_past_the_minute_quota_is_refused() -> None:
    client = _Redis()
    for _ in range(PER_MINUTE):
        _run(check(client, "1.2.3.4", now=1000.0))

    decision = _run(check(client, "1.2.3.4", now=1000.0))
    assert not decision.allowed
    assert decision.scope == "minute"
    # The client is told when to come back rather than left to guess.
    assert decision.retry_after == 60


def test_the_next_minute_starts_a_fresh_allowance() -> None:
    client = _Redis()
    for _ in range(PER_MINUTE + 1):
        _run(check(client, "1.2.3.4", now=1000.0))

    assert _run(check(client, "1.2.3.4", now=1070.0)).allowed


def test_the_daily_quota_still_binds_across_minutes() -> None:
    """The reason both windows exist: three a minute is twenty-four hundred a
    day, which is not a bound on anything."""
    client = _Redis()
    allowed = 0
    for index in range(PER_DAY + 5):
        # A different minute each time, so only the daily window can refuse.
        if _run(check(client, "1.2.3.4", now=1000.0 + index * 60)).allowed:
            allowed += 1

    assert allowed == PER_DAY


def test_daily_refusal_says_so() -> None:
    client = _Redis()
    for index in range(PER_DAY):
        _run(check(client, "1.2.3.4", now=1000.0 + index * 60))

    decision = _run(check(client, "1.2.3.4", now=1000.0 + PER_DAY * 60))
    assert decision.scope == "day"
    assert "明天" in decision.message


def test_callers_are_counted_separately() -> None:
    client = _Redis()
    for _ in range(PER_MINUTE + 1):
        _run(check(client, "1.1.1.1", now=1000.0))

    assert _run(check(client, "2.2.2.2", now=1000.0)).allowed


# --- failure behaviour -----------------------------------------------------


def test_a_dead_redis_lets_the_call_through() -> None:
    """Fails open on purpose. A limiter that takes the feature down when Redis
    restarts trades a bounded cost problem for an outage, and these quotas bound
    spend rather than protect anything — there is no authentication yet."""
    assert _run(check(_Redis(fail=True), "1.2.3.4", now=1000.0)).allowed


# --- identifying the caller behind a proxy ---------------------------------


def test_the_original_client_is_taken_from_the_forwarded_header() -> None:
    """Cloudflare and Caddy sit in front, so `request.client.host` is the proxy
    on every request and would put the entire internet in one bucket."""
    assert caller_id("203.0.113.7, 172.16.0.1", "172.16.0.1") == "203.0.113.7"


def test_the_socket_address_is_used_when_there_is_no_proxy() -> None:
    assert caller_id(None, "203.0.113.7") == "203.0.113.7"


def test_a_blank_forwarded_header_falls_back_rather_than_bucketing_everyone() -> None:
    assert caller_id("", "203.0.113.7") == "203.0.113.7"
    assert caller_id("  ,  ", "203.0.113.7") == "203.0.113.7"


def test_an_unidentifiable_caller_still_gets_a_bucket() -> None:
    # Sharing one bucket is the safe direction: it limits more, not less.
    assert caller_id(None, None) == "unknown"

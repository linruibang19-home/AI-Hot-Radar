"""The RAG operations dashboard is a disposable, bounded read model."""

from __future__ import annotations

import asyncio
import inspect
import json

from ahr.rag import api, cache


class _Redis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: int | None = None

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttl = ex


def test_operations_windows_have_different_keys() -> None:
    assert cache.ops_stats_key(7) != cache.ops_stats_key(30)


def test_operations_snapshot_round_trips_with_a_short_ttl() -> None:
    client = _Redis()
    payload = {"retrieval": {"queries": 225}, "cache": {"hits": 3}}

    asyncio.run(cache.put_ops_stats(client, 30, payload))  # type: ignore[arg-type]
    restored = asyncio.run(cache.get_ops_stats(client, 30))  # type: ignore[arg-type]

    assert restored == payload
    assert client.ttl == cache.OPS_STATS_TTL
    assert 5 <= cache.OPS_STATS_TTL <= 60
    assert json.loads(next(iter(client.store.values()))) == payload


def test_operations_cache_failure_is_only_a_miss() -> None:
    class BrokenRedis:
        async def get(self, key: str) -> str | None:
            raise ConnectionError(key)

    assert asyncio.run(cache.get_ops_stats(BrokenRedis(), 30)) is None  # type: ignore[arg-type]


def test_sync_postgres_aggregation_leaves_the_event_loop() -> None:
    source = inspect.getsource(api.stats)
    assert "asyncio.to_thread(aggregate)" in source
    assert "async with lock" in source
    assert source.count("get_ops_stats") >= 2

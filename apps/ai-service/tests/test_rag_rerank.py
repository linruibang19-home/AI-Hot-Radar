"""Reranker client.

The provider is stubbed. What is worth testing here is not that HTTP works, but
that a malformed or reordered response is refused rather than quietly attaching
every score to the wrong passage — a corruption no query would reveal.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from ahr.rag.rerank import (
    RerankClient,
    RerankConfig,
    RerankUnavailableError,
    build_config_from_env,
)


@asynccontextmanager
async def _client(transport: httpx.MockTransport) -> AsyncIterator[RerankClient]:
    """A client wired to a stub transport.

    `__aenter__` builds its own AsyncClient from the config, so entering the
    real context manager would discard the stub and fire a live request. The
    transport is injected instead, and closed here.
    """
    client = RerankClient(
        config=RerankConfig(
            base_url="https://provider.test/v1",
            api_key="k",
            model="BAAI/bge-reranker-v2-m3",
            max_attempts=1,
        )
    )
    client._client = httpx.AsyncClient(transport=transport, base_url="https://provider.test/v1")
    try:
        yield client
    finally:
        await client._client.aclose()


def _responds(payload: dict[str, object], status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=payload))


async def test_results_are_returned_sorted_by_score() -> None:
    transport = _responds(
        {
            "results": [
                {"index": 0, "relevance_score": 0.11},
                {"index": 2, "relevance_score": 0.93},
                {"index": 1, "relevance_score": 0.55},
            ]
        }
    )
    async with _client(transport) as client:
        scored = await client.rerank("q", ["a", "b", "c"])
    assert [index for index, _ in scored] == [2, 1, 0]


async def test_indices_are_read_from_the_response_not_from_position() -> None:
    # The provider is free to return results in any order. Trusting array
    # position would attach the top score to document 0 here instead of 2.
    transport = _responds(
        {"results": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]}
    )
    async with _client(transport) as client:
        scored = await client.rerank("q", ["a", "b", "c"])
    assert scored[0] == (2, 0.9)


async def test_an_out_of_range_index_is_refused() -> None:
    transport = _responds({"results": [{"index": 7, "relevance_score": 0.9}]})
    async with _client(transport) as client:
        with pytest.raises(RerankUnavailableError, match="index 7"):
            await client.rerank("q", ["a", "b"])


async def test_a_result_without_a_score_is_refused() -> None:
    transport = _responds({"results": [{"index": 0}]})
    async with _client(transport) as client:
        with pytest.raises(RerankUnavailableError, match="malformed"):
            await client.rerank("q", ["a"])


async def test_a_response_without_results_is_refused() -> None:
    transport = _responds({"data": []})
    async with _client(transport) as client:
        with pytest.raises(RerankUnavailableError, match="no results"):
            await client.rerank("q", ["a"])


async def test_server_errors_surface_as_unavailable() -> None:
    transport = _responds({"error": "boom"}, status=503)
    async with _client(transport) as client:
        with pytest.raises(RerankUnavailableError, match="rerank failed"):
            await client.rerank("q", ["a"])


async def test_empty_documents_short_circuit_without_a_call() -> None:
    def fail(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("provider must not be called for an empty candidate set")

    async with _client(httpx.MockTransport(fail)) as client:
        assert await client.rerank("q", []) == []


async def test_use_outside_the_context_manager_is_an_error() -> None:
    client = RerankClient(
        config=RerankConfig(base_url="https://x", api_key="k", model="m"),
    )
    with pytest.raises(RerankUnavailableError, match="context manager"):
        await client.rerank("q", ["a"])


def test_config_falls_back_to_the_embedding_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    # SiliconFlow serves both models from one account; a second set of
    # variables would be two things to keep in sync for no gain.
    monkeypatch.delenv("RERANKER_BASE_URL", raising=False)
    monkeypatch.delenv("RERANKER_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test")
    monkeypatch.setenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    monkeypatch.delenv("RERANKER_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("RERANKER_MAX_ATTEMPTS", raising=False)

    config = build_config_from_env()
    assert config.base_url == "https://api.siliconflow.cn/v1"
    assert config.api_key == "sk-test"
    assert config.timeout_seconds == 20.0
    assert config.max_attempts == 2


def test_runtime_bounds_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://x")
    monkeypatch.setenv("EMBEDDING_API_KEY", "k")
    monkeypatch.setenv("RERANKER_MODEL", "m")
    monkeypatch.setenv("RERANKER_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("RERANKER_MAX_ATTEMPTS", "1")
    config = build_config_from_env()
    assert config.timeout_seconds == 12.5
    assert config.max_attempts == 1


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("RERANKER_TIMEOUT_SECONDS", "61", "between 1 and 60"),
        ("RERANKER_MAX_ATTEMPTS", "1.5", "integer"),
        ("RERANKER_MAX_ATTEMPTS", "4", "between 1 and 3"),
    ],
)
def test_invalid_runtime_bounds_fail_configuration(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, message: str
) -> None:
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://x")
    monkeypatch.setenv("EMBEDDING_API_KEY", "k")
    monkeypatch.setenv("RERANKER_MODEL", "m")
    monkeypatch.setenv(name, value)
    with pytest.raises(RerankUnavailableError, match=message):
        build_config_from_env()


def test_missing_model_is_reported_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://x")
    monkeypatch.setenv("EMBEDDING_API_KEY", "k")
    monkeypatch.delenv("RERANKER_MODEL", raising=False)
    monkeypatch.delenv("RERANKER_BASE_URL", raising=False)
    monkeypatch.delenv("RERANKER_API_KEY", raising=False)

    with pytest.raises(RerankUnavailableError, match="RERANKER_MODEL"):
        build_config_from_env()

"""Embedding client (M4).

The failure that matters here is silent: a vector attached to the wrong chunk,
or a dimension mismatch, produces a working index that returns wrong results.
No query reveals it, so the client validates both before writing.
"""

from __future__ import annotations

import httpx
import pytest

from ahr.rag.embeddings import (
    EMBEDDING_DIMENSIONS,
    MAX_CHARS_PER_INPUT,
    EmbeddingClient,
    EmbeddingConfig,
    EmbeddingUnavailableError,
    build_config_from_env,
)


def make_client(handler, *, dimensions: int = EMBEDDING_DIMENSIONS) -> EmbeddingClient:
    client = EmbeddingClient(
        config=EmbeddingConfig(
            base_url="https://provider.test/v1",
            api_key="k",
            model="BAAI/bge-m3",
            dimensions=dimensions,
            max_attempts=1,
        )
    )
    client._client = httpx.AsyncClient(  # noqa: SLF001 - test seam
        transport=httpx.MockTransport(handler), base_url="https://provider.test/v1"
    )
    return client


def vector(seed: float, dims: int = EMBEDDING_DIMENSIONS) -> list[float]:
    return [seed] * dims


def ok_response(count: int, dims: int = EMBEDDING_DIMENSIONS):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": vector(float(i), dims)} for i in range(count)],
                "usage": {"prompt_tokens": 12},
            },
        )

    return handler


# --- configuration --------------------------------------------------------


def test_missing_configuration_names_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(EmbeddingUnavailableError) as caught:
        build_config_from_env()

    assert "EMBEDDING_BASE_URL" in str(caught.value)
    assert "EMBEDDING_MODEL" in str(caught.value)


def test_configuration_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1/")
    monkeypatch.setenv("EMBEDDING_API_KEY", "secret")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1024")

    config = build_config_from_env()

    # The trailing slash would double up against the "/embeddings" path.
    assert config.base_url == "https://api.siliconflow.cn/v1"
    assert config.dimensions == 1024


# --- ordering -------------------------------------------------------------


@pytest.mark.asyncio
async def test_vectors_come_back_in_request_order() -> None:
    client = make_client(ok_response(3))
    vectors = await client.embed(["a", "b", "c"])
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]


@pytest.mark.asyncio
async def test_a_reordered_response_is_re_sorted_by_index() -> None:
    """The caller pairs vectors onto chunk ids positionally, so a reordered
    response would attach every vector to the wrong chunk — corruption no query
    would reveal."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 2, "embedding": vector(2.0)},
                    {"index": 0, "embedding": vector(0.0)},
                    {"index": 1, "embedding": vector(1.0)},
                ],
                "usage": {"prompt_tokens": 3},
            },
        )

    vectors = await make_client(handler).embed(["a", "b", "c"])
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]


@pytest.mark.asyncio
async def test_a_short_response_is_rejected() -> None:
    """Fewer vectors than inputs would silently shift every later pairing."""
    with pytest.raises(EmbeddingUnavailableError, match="2 vectors for 3 inputs"):
        await make_client(ok_response(2)).embed(["a", "b", "c"])


# --- dimensionality -------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_dimensionality_is_rejected() -> None:
    """pgvector cannot compare vectors of different widths; writing one poisons
    the column rather than erroring at query time."""
    client = make_client(ok_response(1, dims=1536), dimensions=1024)
    with pytest.raises(EmbeddingUnavailableError, match="1024 dimensions"):
        await client.embed(["a"])


def test_pinned_dimensionality_matches_the_migration() -> None:
    """V012 declares vector(1024); a mismatch here corrupts the index."""
    assert EMBEDDING_DIMENSIONS == 1024


# --- input handling -------------------------------------------------------


@pytest.mark.asyncio
async def test_long_input_is_truncated_before_sending() -> None:
    """Truncating here makes the cut visible in our logs instead of being
    applied silently by the provider."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": vector(0.0)}], "usage": {}}
        )

    await make_client(handler).embed(["x" * 50_000])
    assert len(seen["input"][0]) == MAX_CHARS_PER_INPUT  # type: ignore[index]


@pytest.mark.asyncio
async def test_empty_batch_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not be called")

    assert await make_client(handler).embed([]) == []


@pytest.mark.asyncio
async def test_use_outside_the_context_manager_is_an_error() -> None:
    client = EmbeddingClient(
        config=EmbeddingConfig(base_url="https://x.test", api_key="k", model="m")
    )
    with pytest.raises(EmbeddingUnavailableError, match="context manager"):
        await client.embed(["a"])


# --- failures -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rate_limit_raises_rather_than_returning_partial_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    client = make_client(handler)
    with pytest.raises(EmbeddingUnavailableError):
        await client.embed(["a"])
    assert client.usage.failures == 1


@pytest.mark.asyncio
async def test_usage_is_recorded_for_a_successful_call() -> None:
    client = make_client(ok_response(2))
    await client.embed(["a", "b"])
    assert client.usage.calls == 1
    assert client.usage.prompt_tokens == 12

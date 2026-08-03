"""Embedding client (M4).

Separate from `processing/llm.py` because the two are different providers with
different failure modes: DeepSeek writes prose and a failure means a missing
summary, while the embedding provider populates the retrieval index and a
failure means a chunk is invisible to search. Mixing them would also hide that
they are billed and rate-limited independently.

SiliconFlow exposes an OpenAI-compatible `/embeddings` endpoint, so this stays a
thin HTTP client rather than pulling in a vendor SDK — AHR-ARCH-200 §5 wants
every external call bounded by our own timeouts, which an SDK would obscure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Pinned by V012: pgvector cannot compare vectors of differing dimensionality,
# so a mismatch here corrupts the index rather than erroring loudly.
EMBEDDING_DIMENSIONS = 1024

# Requests per call. Large enough that 3800 chunks is ~60 calls, small enough
# that one failure does not discard minutes of work.
DEFAULT_BATCH_SIZE = 64

# Chunks run to a few thousand characters; the model truncates at 8192 tokens.
# Truncating here instead means the cut is visible in our own logs rather than
# silently applied server-side.
MAX_CHARS_PER_INPUT = 6000


class EmbeddingUnavailableError(RuntimeError):
    """Provider not configured or not reachable."""


@dataclass
class EmbeddingUsage:
    calls: int = 0
    prompt_tokens: int = 0
    latency_ms: int = 0
    failures: int = 0
    retries: int = 0


@dataclass
class EmbeddingConfig:
    base_url: str
    api_key: str
    model: str
    dimensions: int = EMBEDDING_DIMENSIONS
    timeout_seconds: float = 60.0
    max_attempts: int = 3


def build_config_from_env() -> EmbeddingConfig:
    base_url = os.environ.get("EMBEDDING_BASE_URL", "").strip()
    api_key = os.environ.get("EMBEDDING_API_KEY", "").strip()
    model = os.environ.get("EMBEDDING_MODEL", "").strip()

    missing = [
        name
        for name, value in (
            ("EMBEDDING_BASE_URL", base_url),
            ("EMBEDDING_API_KEY", api_key),
            ("EMBEDDING_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise EmbeddingUnavailableError(f"missing environment variables: {', '.join(missing)}")

    return EmbeddingConfig(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        model=model,
        dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS", EMBEDDING_DIMENSIONS)),
    )


@dataclass
class EmbeddingClient:
    config: EmbeddingConfig
    usage: EmbeddingUsage = field(default_factory=EmbeddingUsage)
    _client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> EmbeddingClient:
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def model_name(self) -> str:
        return self.config.model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch, preserving order.

        Order matters more than it looks: the caller pairs the results back onto
        chunk ids positionally, so a reordered response would attach every
        vector to the wrong chunk — a corruption that no query would reveal.
        """
        if self._client is None:
            raise EmbeddingUnavailableError("client used outside its context manager")
        if not texts:
            return []

        payload = {
            "model": self.config.model,
            "input": [text[:MAX_CHARS_PER_INPUT] for text in texts],
        }

        started = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                response = await self._client.post("/embeddings", json=payload)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"provider returned {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                body = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                self.usage.retries += 1
                if attempt == self.config.max_attempts:
                    self.usage.failures += 1
                    raise EmbeddingUnavailableError(
                        f"embedding failed after {attempt} attempts: {exc}"
                    ) from exc
                # Exponential backoff: a rate limit clears with time, and
                # hammering it makes the window longer.
                await asyncio.sleep(2**attempt)
        else:  # pragma: no cover - loop always breaks or raises
            raise EmbeddingUnavailableError(str(last_error))

        rows = body.get("data") or []
        if len(rows) != len(texts):
            raise EmbeddingUnavailableError(
                f"provider returned {len(rows)} vectors for {len(texts)} inputs"
            )

        # The response carries an explicit index; trusting array order alone
        # would silently mis-pair vectors if the provider ever reorders.
        ordered = sorted(rows, key=lambda row: row.get("index", 0))
        vectors = [row["embedding"] for row in ordered]

        for vector in vectors:
            if len(vector) != self.config.dimensions:
                raise EmbeddingUnavailableError(
                    f"expected {self.config.dimensions} dimensions, got {len(vector)}; "
                    "the column type and the model must agree"
                )

        self.usage.calls += 1
        self.usage.prompt_tokens += int((body.get("usage") or {}).get("prompt_tokens", 0))
        self.usage.latency_ms += int((time.monotonic() - started) * 1000)
        return vectors


def build_client_from_env() -> EmbeddingClient:
    return EmbeddingClient(config=build_config_from_env())

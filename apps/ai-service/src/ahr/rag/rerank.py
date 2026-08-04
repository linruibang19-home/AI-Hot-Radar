"""Cross-encoder reranking (M4, B4).

B3 produced the textbook case for a reranker. Fusing dense with sparse lifted
Recall@20 from 0.8876 to **0.9036** while MRR fell from 0.7630 to **0.6911** —
more of the right documents entered the candidate set, and they ranked worse.
`metrics.py` states what that combination means: the answer is present but
buried, and reranking is where the gain is.

So B4 has a gate rather than an aspiration. From
`docs/design/m4-rag-evaluation.md`: it enters the MVP only if it pulls MRR back
above B1's 0.7630 while holding B3's Recall@20 of 0.9036 — and only if the
latency it costs is worth it. A reranker that improves nDCG@10 by under 3% while
doubling p95 does not ship.

Unlike the bi-encoder, a cross-encoder reads the question and the passage
together, which is why it can tell "MXFP4" from "NVFP4" where cosine similarity
could not. It is also why it cannot be precomputed: every pair costs a forward
pass, so it runs over tens of candidates, never over the corpus.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# AHR-RAG-400 §6: fusion hands at most 100 candidates to the reranker, which
# keeps 24. Reranking more would cost latency the evaluation has to justify.
DEFAULT_CANDIDATE_LIMIT = 100
DEFAULT_TOP_N = 24

# The cross-encoder truncates long inputs itself; cutting here keeps the
# truncation visible in our own logs rather than silently applied server-side.
MAX_DOCUMENT_CHARS = 4000


class RerankUnavailableError(RuntimeError):
    """Provider not configured or not reachable."""


@dataclass
class RerankUsage:
    calls: int = 0
    documents: int = 0
    latency_ms: int = 0
    failures: int = 0
    retries: int = 0


@dataclass
class RerankConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0
    max_attempts: int = 3


def build_config_from_env() -> RerankConfig:
    # Reuses the embedding provider's credentials: SiliconFlow serves both
    # bge-m3 and bge-reranker-v2-m3 from the same account and base URL, and a
    # second set of variables would be two things to keep in sync for no gain.
    base_url = (
        os.environ.get("RERANKER_BASE_URL", "").strip()
        or os.environ.get("EMBEDDING_BASE_URL", "").strip()
    )
    api_key = (
        os.environ.get("RERANKER_API_KEY", "").strip()
        or os.environ.get("EMBEDDING_API_KEY", "").strip()
    )
    model = os.environ.get("RERANKER_MODEL", "").strip()

    missing = [
        name
        for name, value in (
            ("RERANKER_BASE_URL or EMBEDDING_BASE_URL", base_url),
            ("RERANKER_API_KEY or EMBEDDING_API_KEY", api_key),
            ("RERANKER_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RerankUnavailableError(f"reranker not configured: missing {', '.join(missing)}")

    return RerankConfig(base_url=base_url, api_key=api_key, model=model)


@dataclass
class RerankClient:
    config: RerankConfig
    usage: RerankUsage = field(default_factory=RerankUsage)
    _client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> RerankClient:
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

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int = DEFAULT_TOP_N,
    ) -> list[tuple[int, float]]:
        """Score `documents` against `query`; return `(original_index, score)`.

        Indices are the caller's, not the provider's ordering. The response is
        read through its explicit `index` field for the same reason the
        embedding client sorts by it: positional trust would silently attach
        every score to the wrong passage, and no query would reveal it.
        """
        if self._client is None:
            raise RerankUnavailableError("client used outside its context manager")
        if not documents:
            return []

        payload = {
            "model": self.config.model,
            "query": query,
            "documents": [doc[:MAX_DOCUMENT_CHARS] for doc in documents],
            "top_n": min(top_n, len(documents)),
        }

        started = time.monotonic()
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                response = await self._client.post("/rerank", json=payload)
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
                self.usage.retries += 1
                if attempt == self.config.max_attempts:
                    self.usage.failures += 1
                    raise RerankUnavailableError(
                        f"rerank failed after {attempt} attempts: {exc}"
                    ) from exc
                await asyncio.sleep(2**attempt)

        self.usage.calls += 1
        self.usage.documents += len(documents)
        self.usage.latency_ms += int((time.monotonic() - started) * 1000)

        results = body.get("results")
        if results is None:
            raise RerankUnavailableError("rerank response carried no results")

        scored: list[tuple[int, float]] = []
        for row in results:
            index = row.get("index")
            score = row.get("relevance_score", row.get("score"))
            if index is None or score is None:
                raise RerankUnavailableError(f"malformed rerank result: {row!r}")
            if not 0 <= int(index) < len(documents):
                raise RerankUnavailableError(
                    f"rerank returned index {index} for {len(documents)} documents"
                )
            scored.append((int(index), float(score)))

        scored.sort(key=lambda pair: -pair[1])
        return scored


def build_client_from_env() -> RerankClient:
    return RerankClient(config=build_config_from_env())

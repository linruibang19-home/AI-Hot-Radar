"""LLM client for content enrichment.

AHR-ARCH-200 §5 bounds LLM calls: 5s connect / 60s read, 2 attempts, retry only
on timeout, 429 and 5xx. AHR-SPEC-000 §8 allows exactly one repair attempt when
the response fails schema validation, after which the document becomes a dead
letter rather than being written as free text.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from ahr.processing.schemas import (
    PROMPT_VERSION,
    REPAIR_PROMPT,
    SYSTEM_PROMPT,
    EnrichmentResult,
)

logger = logging.getLogger(__name__)

# Enough body to judge an article without paying for a whole paper.
MAX_BODY_CHARS = 6000

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LlmUnavailableError(RuntimeError):
    """The provider could not be reached or is not configured.

    Distinct from a schema failure: the site must keep serving existing content
    when the model is down (AHR-ROADMAP-800 M2 acceptance).
    """


class EnrichmentSchemaError(RuntimeError):
    """The model answered but the answer does not satisfy the contract."""


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    connect_timeout: float = 5.0
    read_timeout: float = 60.0
    max_attempts: int = 2
    temperature: float = 0.2


def _strip_code_fence(text: str) -> str:
    """Models often wrap JSON in a markdown fence despite instructions."""
    match = _JSON_BLOCK_RE.search(text)
    return match.group(1) if match else text.strip()


class LlmClient:
    """Chat-completions client for OpenAI-compatible providers (DeepSeek)."""

    def __init__(self, config: LlmConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> LlmClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self._config.connect_timeout,
                    read=self._config.read_timeout,
                    write=self._config.read_timeout,
                    pool=self._config.connect_timeout,
                ),
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _complete(self, messages: list[dict[str, str]]) -> str:
        if self._client is None:
            raise RuntimeError("LlmClient must be used as an async context manager")

        payload = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "stream": False,
            # Providers that support it return strict JSON; others ignore it and
            # the fence-stripping fallback handles the difference.
            "response_format": {"type": "json_object"},
        }

        last_error: Exception | None = None
        for _attempt in range(self._config.max_attempts):
            try:
                response = await self._client.post(
                    f"{self._config.base_url.rstrip('/')}/chat/completions", json=payload
                )
            except httpx.HTTPError as exc:
                last_error = exc
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = LlmUnavailableError(f"provider returned {response.status_code}")
                continue
            if response.status_code >= 400:
                # 4xx other than 429 will not succeed on retry.
                raise LlmUnavailableError(
                    f"provider rejected request: {response.status_code} {response.text[:200]}"
                )

            body = response.json()
            return str(body["choices"][0]["message"]["content"])

        raise LlmUnavailableError(
            f"llm unavailable after {self._config.max_attempts} attempts: {last_error}"
        )

    async def enrich(self, *, title: str, body_text: str, source_name: str) -> EnrichmentResult:
        """Structure one article, with a single repair attempt on schema failure."""
        user_prompt = (
            f"来源：{source_name}\n原标题：{title}\n\n正文：\n{body_text[:MAX_BODY_CHARS]}"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        raw = await self._complete(messages)
        try:
            return EnrichmentResult.model_validate_json(_strip_code_fence(raw))
        except (ValidationError, ValueError) as exc:
            # Python unbinds the `as` name when the except block exits, so the
            # message has to be captured here to survive into the repair turn.
            first_error = str(exc)
            logger.info("enrichment schema failed, attempting one repair: %s", first_error)

        messages.extend(
            [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": REPAIR_PROMPT.format(error=first_error[:400])},
            ]
        )
        repaired = await self._complete(messages)
        try:
            return EnrichmentResult.model_validate_json(_strip_code_fence(repaired))
        except (ValidationError, ValueError) as second_error:
            raise EnrichmentSchemaError(
                f"schema validation failed after one repair: {second_error}"
            ) from second_error


def build_client_from_env() -> LlmClient:
    """Construct a client from environment configuration."""
    import os

    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()

    if not (base_url and api_key and model):
        raise LlmUnavailableError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must all be set")

    return LlmClient(LlmConfig(base_url=base_url, api_key=api_key, model=model))


def prompt_version() -> str:
    return PROMPT_VERSION


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)

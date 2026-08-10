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
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

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


@dataclass
class TokenUsage:
    """Actual usage reported by the provider, accumulated across attempts.

    Taken from the response rather than estimated from characters: tokenisation
    and prompt caching both make character counts a poor proxy for spend.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    attempts: int = 0
    latency_ms: int = 0

    def add(self, payload: dict[str, Any] | None, *, elapsed_ms: int) -> None:
        self.attempts += 1
        self.latency_ms += elapsed_ms
        if not payload:
            return
        self.prompt_tokens += int(payload.get("prompt_tokens") or 0)
        self.completion_tokens += int(payload.get("completion_tokens") or 0)
        self.cached_tokens += int(payload.get("prompt_cache_hit_tokens") or 0)


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

    async def _complete(
        self, messages: list[dict[str, str]], usage: TokenUsage, *, json_mode: bool = True
    ) -> str:
        if self._client is None:
            raise RuntimeError("LlmClient must be used as an async context manager")

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "stream": False,
        }
        if json_mode:
            # Providers that support it return strict JSON; others ignore it and
            # the fence-stripping fallback handles the difference. Prose calls
            # must not set it, or the model wraps the summary in a JSON object.
            payload["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for _attempt in range(self._config.max_attempts):
            started = time.monotonic()
            try:
                response = await self._client.post(
                    f"{self._config.base_url.rstrip('/')}/chat/completions", json=payload
                )
            except httpx.HTTPError as exc:
                last_error = exc
                usage.add(None, elapsed_ms=int((time.monotonic() - started) * 1000))
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
            usage.add(body.get("usage"), elapsed_ms=int((time.monotonic() - started) * 1000))
            return str(body["choices"][0]["message"]["content"])

        raise LlmUnavailableError(
            f"llm unavailable after {self._config.max_attempts} attempts: {last_error}"
        )

    @property
    def model_name(self) -> str:
        return self._config.model

    async def summarize(
        self, *, system_prompt: str, user_prompt: str, json_mode: bool = False
    ) -> tuple[str, TokenUsage]:
        """Completion for narrative output or a caller-declared JSON contract.

        Narrative callers keep the default. RAG supplies a JSON schema in its
        prompt and opts in so compatible providers enforce the same contract at
        transport level; the downstream parser remains the final validator.
        """
        usage = TokenUsage()
        text = await self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            usage,
            json_mode=json_mode,
        )
        return text, usage

    async def stream_summarize(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        usage: TokenUsage,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """`summarize`, delivered as it is produced.

        Yields raw content deltas exactly as the provider sends them — no
        interpretation happens here, because what the deltas *mean* depends on
        the caller's contract with the model, and the RAG path has a strict one.

        Deliberately not retried. `_complete` can retry because a failed attempt
        produced nothing the caller has seen; here the first token has already
        left the building, and a retry would restart the answer from the
        beginning on top of one already partly on screen.
        """
        if self._client is None:
            raise RuntimeError("LlmClient must be used as an async context manager")

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._config.temperature,
            "stream": True,
            # Providers only report token counts on the final chunk when asked.
            # Without this the cost of every streamed answer would be invisible,
            # and `llm_usage` is meant to hold provider-reported numbers rather
            # than estimates.
            "stream_options": {"include_usage": True},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.monotonic()
        try:
            async with self._client.stream(
                "POST", f"{self._config.base_url.rstrip('/')}/chat/completions", json=payload
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread())[:200].decode("utf-8", "replace")
                    raise LlmUnavailableError(
                        f"provider rejected stream: {response.status_code} {body}"
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        # A malformed frame is not worth failing the answer over;
                        # the caller validates the assembled result regardless.
                        continue

                    if chunk.get("usage"):
                        usage.add(chunk["usage"], elapsed_ms=0)

                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            yield str(piece)
        except httpx.HTTPError as exc:
            raise LlmUnavailableError(f"llm stream failed: {exc}") from exc
        finally:
            usage.latency_ms += int((time.monotonic() - started) * 1000)
            if not usage.attempts:
                usage.attempts = 1

    async def enrich(
        self, *, title: str, body_text: str, source_name: str
    ) -> tuple[EnrichmentResult, TokenUsage]:
        """Structure one article, with a single repair attempt on schema failure."""
        user_prompt = (
            f"来源：{source_name}\n原标题：{title}\n\n正文：\n{body_text[:MAX_BODY_CHARS]}"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        usage = TokenUsage()
        raw = await self._complete(messages, usage)
        try:
            return EnrichmentResult.model_validate_json(_strip_code_fence(raw)), usage
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
        repaired = await self._complete(messages, usage)
        try:
            return EnrichmentResult.model_validate_json(_strip_code_fence(repaired)), usage
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

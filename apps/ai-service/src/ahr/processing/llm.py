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
    model_config_version: int | None = None
    input_cny_per_million: float | None = None
    cached_input_cny_per_million: float | None = None
    output_cny_per_million: float | None = None


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
        self,
        messages: list[dict[str, str]],
        usage: TokenUsage,
        *,
        json_mode: bool = True,
        temperature: float | None = None,
    ) -> str:
        if self._client is None:
            raise RuntimeError("LlmClient must be used as an async context manager")

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature if temperature is None else temperature,
            "stream": False,
        }
        if self._config.model.startswith("deepseek-v4-"):
            # V4 defaults to thinking. ADR-0027 keeps it explicitly disabled
            # until its different latency, pricing and JSON behaviour have a
            # dedicated regression rather than changing them with a model name.
            payload["thinking"] = {"type": "disabled"}
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

    @property
    def model_config_version(self) -> int | None:
        return self._config.model_config_version

    @property
    def price_snapshot(self) -> tuple[float | None, float | None, float | None]:
        return (
            self._config.input_cny_per_million,
            self._config.cached_input_cny_per_million,
            self._config.output_cny_per_million,
        )

    async def summarize(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        temperature: float | None = None,
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
            temperature=temperature,
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
        if self._config.model.startswith("deepseek-v4-"):
            payload["thinking"] = {"type": "disabled"}
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


def _decrypt_credential(payload: str) -> str:
    """Open the AES-256-GCM envelope Core API wrote (V027).

    The master key stays in the environment on both sides, so a database dump
    without it decrypts to nothing. GCM is authenticated: a corrupted or
    tampered ciphertext raises here rather than producing plausible bytes that
    would then be sent to a provider as a credential.
    """
    import os
    from base64 import b64decode, urlsafe_b64decode

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    master = os.environ.get("LLM_CREDENTIAL_MASTER_KEY", "").strip()
    if not master:
        raise LlmUnavailableError("LLM_CREDENTIAL_MASTER_KEY is not set")
    try:
        key = b64decode(master)
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same misconfiguration
        raise LlmUnavailableError("LLM_CREDENTIAL_MASTER_KEY is not valid base64") from exc
    if len(key) != 32:
        raise LlmUnavailableError("LLM_CREDENTIAL_MASTER_KEY must decode to 32 bytes")

    parts = payload.split(".", 2)
    if len(parts) != 3 or parts[0] != "v1":
        raise LlmUnavailableError("stored credential envelope is not recognised")
    try:
        # Base64url without padding, matching Java's getUrlEncoder().withoutPadding().
        nonce = urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        sealed = urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        return AESGCM(key).decrypt(nonce, sealed, None).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - a wrong key and a bad envelope mean the same thing
        raise LlmUnavailableError("stored credential could not be decrypted") from exc


# What V027 seeds, and what the console writes back when an operator undoes a
# saved provider. Either field carrying it means "read the environment".
_ENVIRONMENT_MARKER = "env://LLM_BASE_URL"


def _provider_from_database(cursor: Any, env_base_url: str, env_api_key: str) -> tuple[str, str]:
    """The address and key to call with, preferring the stored ones.

    Falls back per field rather than all-or-nothing: V027 seeds the row pointing
    at the environment, so a deployment that has never used the console must
    behave exactly as it did before the migration — and an operator who resets
    the provider has to get that behaviour back, not a service that refuses to
    start because a column is null.
    """
    cursor.execute(
        """
        SELECT base_url, api_key_ciphertext
          FROM generation_provider_config
         WHERE singleton_key = 1
        """
    )
    row = cursor.fetchone()
    if row is None:
        return env_base_url, env_api_key

    stored_url, ciphertext = str(row[0] or ""), row[1]
    base_url = env_base_url if stored_url == _ENVIRONMENT_MARKER or not stored_url else stored_url
    api_key = env_api_key if ciphertext is None else _decrypt_credential(str(ciphertext))
    return base_url, api_key


def build_client_from_env() -> LlmClient:
    """Construct the generation client, using PostgreSQL in a running deployment.

    The model is a product setting and comes from PostgreSQL (ADR-0027). Since
    V027 the provider address and key do too, falling back to `LLM_BASE_URL` /
    `LLM_API_KEY` whenever the console has not overridden them — which is the
    state every existing deployment migrates into. `LLM_MODEL` remains only for
    isolated tests and tools that intentionally have no `DATABASE_URL`.
    """
    import os

    import psycopg

    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url and all(
        os.environ.get(name, "").strip()
        for name in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    ):
        # Local/production Compose deliberately passes discrete values so a
        # password containing URL syntax cannot be truncated (ahr.config).
        from ahr.config import get_settings

        database_url = get_settings().database_url
    model = os.environ.get("LLM_MODEL", "").strip()

    if database_url:
        try:
            with (
                psycopg.connect(database_url, connect_timeout=5) as connection,
                connection.cursor() as cursor,
            ):
                # Provider first: the model query decides *which* model, this
                # decides where to send it and with what key.
                base_url, api_key = _provider_from_database(cursor, base_url, api_key)
                cursor.execute(
                    """
                    SELECT c.model_id, c.version,
                           m.input_cny_per_million,
                           m.cached_input_cny_per_million,
                           m.output_cny_per_million
                      FROM generation_model_config c
                      JOIN generation_model_catalog m ON m.model_id = c.model_id
                     WHERE c.singleton_key = 1 AND m.enabled
                    """
                )
                row = cursor.fetchone()
        except psycopg.Error as exc:
            raise LlmUnavailableError(f"generation model setting unavailable: {exc}") from exc
        if row is None:
            raise LlmUnavailableError("generation model setting is missing or disabled")
        # Checked after the row is resolved, not before: since V027 the console
        # can supply both, so a deployment with no LLM_BASE_URL in its
        # environment is legitimate as long as the database carries one.
        if not (base_url and api_key):
            raise LlmUnavailableError(
                "no generation provider configured: set it in the console, "
                "or set LLM_BASE_URL and LLM_API_KEY"
            )
        model = str(row[0])
        return LlmClient(
            LlmConfig(
                base_url=base_url,
                api_key=api_key,
                model=model,
                model_config_version=int(row[1]),
                input_cny_per_million=float(row[2]),
                cached_input_cny_per_million=float(row[3]),
                output_cny_per_million=float(row[4]),
            )
        )

    if not (base_url and api_key):
        raise LlmUnavailableError("LLM_BASE_URL and LLM_API_KEY must both be set")
    if not model:
        raise LlmUnavailableError("LLM_MODEL must be set when DATABASE_URL is absent")

    return LlmClient(LlmConfig(base_url=base_url, api_key=api_key, model=model))


def prompt_version() -> str:
    return PROMPT_VERSION


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)

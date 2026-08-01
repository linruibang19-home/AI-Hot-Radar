"""Bounded HTTP client for source fetching.

Implements `global_http` from config/ingestion-profiles.yaml: timeouts, redirect
limit, response size cap, conditional requests and exponential backoff with full
jitter. AHR-ARCH-200 §5 makes these limits mandatory for every external call.

Redirects are followed manually so the SSRF guard runs on each hop; httpx's own
redirect handling would connect before we could inspect the target.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from ahr.ingestion.errors import (
    AccessRestrictedError,
    NotFoundError,
    RateLimitedError,
    ResponseTooLargeError,
    TransientError,
)
from ahr.ingestion.ssrf import resolve_and_validate

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class HttpConfig:
    user_agent: str = "AIHotRadarBot/1.0 (+https://example.com/bot)"
    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    max_response_bytes: int = 10 * 1024 * 1024
    redirect_limit: int = 5
    attempts: int = 3
    base_delay_ms: int = 500
    max_delay_ms: int = 30_000
    allow_http: bool = False
    # Longest a single fetch may block on a rate-limit reset before deferring
    # to the scheduler.
    max_rate_limit_wait: float = 30.0


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified")

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")


def _backoff_delay(attempt: int, config: HttpConfig) -> float:
    """Exponential backoff with full jitter.

    Full jitter (random between 0 and the cap) rather than fixed delays, so a
    batch of sources failing together does not retry in lockstep.
    """
    capped = min(config.base_delay_ms * (2**attempt), config.max_delay_ms)
    return random.uniform(0, capped) / 1000.0


def _seconds_until_reset(value: str | None) -> float | None:
    """Seconds until an `X-RateLimit-Reset` epoch timestamp."""
    if not value:
        return None
    try:
        reset_at = float(value)
    except ValueError:
        return None
    remaining = reset_at - datetime.now(UTC).timestamp()
    return max(remaining, 0.0)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        # HTTP-date form; treat as a short pause rather than parsing calendars.
        return 60.0


class HttpFetcher:
    """Async HTTP client enforcing the project's fetch policy."""

    def __init__(
        self,
        config: HttpConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        validate_target: Callable[[str, bool], object] | None = None,
    ) -> None:
        self.config = config or HttpConfig()
        self._client = client
        self._owns_client = client is None
        # Injectable so offline tests can skip DNS entirely; production always
        # uses the real resolver-backed guard.
        self._validate_target = validate_target or (
            lambda url, allow_http: resolve_and_validate(url, allow_http=allow_http)
        )

    async def __aenter__(self) -> HttpFetcher:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self.config.connect_timeout,
                    read=self.config.read_timeout,
                    write=self.config.read_timeout,
                    pool=self.config.connect_timeout,
                ),
                follow_redirects=False,
                headers={"User-Agent": self.config.user_agent},
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        """GET `url`, retrying transient failures.

        Raises the ingestion error matching the final failure; callers map that
        to a source state rather than inspecting status codes themselves.
        """
        if self._client is None:
            raise RuntimeError("HttpFetcher must be used as an async context manager")

        request_headers = dict(headers or {})
        if etag:
            request_headers["If-None-Match"] = etag
        if last_modified:
            request_headers["If-Modified-Since"] = last_modified

        last_error: Exception | None = None
        for attempt in range(self.config.attempts):
            if attempt:
                delay = _backoff_delay(attempt - 1, self.config)
                if isinstance(last_error, RateLimitedError) and last_error.retry_after:
                    # A quota reset can be an hour out; blocking the worker that
                    # long would stall every other source. Wait only briefly and
                    # let the caller reschedule, preserving retry_after so the
                    # scheduler knows when the source becomes available again.
                    if last_error.retry_after > self.config.max_rate_limit_wait:
                        raise last_error
                    delay = max(delay, last_error.retry_after)
                await asyncio.sleep(delay)

            try:
                return await self._fetch_once(url, request_headers)
            except (TransientError, RateLimitedError) as exc:
                last_error = exc
                continue

        assert last_error is not None
        raise last_error

    async def _fetch_once(self, url: str, headers: dict[str, str]) -> FetchResult:
        assert self._client is not None

        # Many feeds still publish http:// links for sites that serve https and
        # redirect. Upgrading here keeps the transport-security policy intact
        # while avoiding a spurious SSRF rejection of a healthy public host.
        current = url
        if current.startswith("http://") and not self.config.allow_http:
            current = "https://" + current[len("http://") :]

        for _ in range(self.config.redirect_limit + 1):
            # Re-validate every hop: a public host may redirect to a private one.
            self._validate_target(current, self.config.allow_http)

            try:
                response = await self._client.get(current, headers=headers)
            except httpx.TimeoutException as exc:
                raise TransientError(f"timeout fetching {current}: {exc}") from exc
            except httpx.HTTPError as exc:
                raise TransientError(f"transport error for {current}: {exc}") from exc

            # 304 is a 3xx status but not a redirect: it is the successful
            # answer to a conditional request and carries no Location header.
            if response.status_code == 304:
                return self._to_result(url, current, response)

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise TransientError(f"redirect without location from {current}")
                current = str(httpx.URL(current).join(location))
                continue

            return self._to_result(url, current, response)

        raise TransientError(f"redirect limit exceeded for {url}")

    def _to_result(self, requested: str, final: str, response: httpx.Response) -> FetchResult:
        status = response.status_code
        headers = {k.lower(): v for k, v in response.headers.items()}

        if status == 429:
            raise RateLimitedError(
                f"rate limited by {final}",
                retry_after=_parse_retry_after(headers.get("retry-after")),
            )
        if status == 403 and headers.get("x-ratelimit-remaining") == "0":
            # GitHub signals quota exhaustion with 403 plus a zeroed remaining
            # counter rather than 429. Treating it as ACCESS_RESTRICTED would
            # permanently quarantine a perfectly healthy source.
            raise RateLimitedError(
                f"rate limit exhausted for {final}",
                retry_after=_seconds_until_reset(headers.get("x-ratelimit-reset")),
            )
        if status in (401, 403):
            raise AccessRestrictedError(f"access restricted ({status}) for {final}")
        if status in (404, 410):
            raise NotFoundError(f"not found ({status}) for {final}")
        if status in RETRY_STATUSES:
            raise TransientError(f"retryable status {status} for {final}")
        if status >= 400:
            raise TransientError(f"unexpected status {status} for {final}")

        body = response.content
        if len(body) > self.config.max_response_bytes:
            raise ResponseTooLargeError(
                f"{final} returned {len(body)} bytes, limit {self.config.max_response_bytes}"
            )

        return FetchResult(
            url=requested,
            final_url=final,
            status_code=status,
            headers=headers,
            body=b"" if status == 304 else body,
        )

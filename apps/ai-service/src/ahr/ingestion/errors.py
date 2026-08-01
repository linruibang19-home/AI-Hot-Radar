"""Error taxonomy for ingestion.

AHR-INGEST-1000 §12 fixes which failures may be retried. Encoding that decision
in the exception type keeps the retry policy in one place instead of scattering
status-code checks across adapters.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class. `code` is persisted to `last_error_code`."""

    code = "INGESTION_ERROR"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class TransientError(IngestionError):
    """DNS failures, timeouts, 408 and 5xx: retry with backoff."""

    code = "TRANSIENT"
    retryable = True


class RateLimitedError(TransientError):
    """429. `retry_after` seconds must be honoured when the server supplies it."""

    code = "RATE_LIMITED"

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AccessRestrictedError(IngestionError):
    """401/403, login walls, captchas and paywalls. Never retried, never bypassed."""

    code = "ACCESS_RESTRICTED"


class NotFoundError(IngestionError):
    """404/410. Re-check canonical; disable the entry if it persists."""

    code = "NOT_FOUND"


class SsrfBlockedError(IngestionError):
    """Target resolved to a private, loopback or link-local address."""

    code = "SSRF_BLOCKED"


class ResponseTooLargeError(IngestionError):
    """Body exceeded `max_response_bytes`."""

    code = "RESPONSE_TOO_LARGE"


class ParseFailedError(IngestionError):
    """Structure changed such that extraction failed. Save a fixture."""

    code = "PARSE_FAILED"


class FulltextRejectedError(IngestionError):
    """Body failed the quality gate. A summary must never be substituted."""

    code = "FULLTEXT_REJECTED"

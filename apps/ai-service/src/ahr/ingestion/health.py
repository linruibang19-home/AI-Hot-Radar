"""How a failed poll changes a source's verdict (AHR-SOURCE-900 §5).

The spec sets a ladder: three consecutive failures demote a source to
`DEGRADED`, and only twenty-four hours of continuous failure quarantine it.
The pipeline used to skip both rungs and quarantine on the first error, which
turned one DNS hiccup into eighteen first-party sources — OpenAI, Anthropic,
Hugging Face, arXiv, vLLM, 量子位 — reading as quarantined on the admin page
while every one of them resolved fine on the next tick.

Two ideas keep this honest:

* **A failure the taxonomy calls retryable is not a verdict about the source.**
  `errors.py` already decides which codes may be retried; this module consumes
  that decision instead of re-deriving it from status codes.
* **"Failing for 24 hours" needs both halves.** `last_success_at` alone is a bad
  proxy: a source polled every three hours that succeeded 25 hours ago and then
  fails once would trip the window on a single error. Requiring the failure
  count as well means the elapsed time is only consulted once the failures are
  demonstrably consecutive.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# §5: "连续 3 次失败 … 进入 DEGRADED".
DEGRADE_AFTER_FAILURES = 3

# §5: "连续 24 小时失败进入 QUARANTINED".
QUARANTINE_AFTER = timedelta(hours=24)


def next_state_after_failure(
    *,
    current_state: str,
    error_code: str,
    retryable: bool,
    consecutive_failures: int,
    last_success_at: datetime | None,
    created_at: datetime | None,
    now: datetime,
) -> str:
    """Return the runtime state to store after a poll failed.

    `consecutive_failures` is the count *before* this failure; the caller has
    not incremented it yet.
    """
    # Quota exhaustion says nothing about source health (V003), so it keeps its
    # own state and never enters the ladder.
    if error_code == "RATE_LIMITED":
        return "RATE_LIMITED"

    # A login wall, a 404 or an SSRF verdict will not resolve itself by being
    # retried, and continuing to hammer one is the behaviour §7 forbids.
    if not retryable:
        return "QUARANTINED"

    failures = consecutive_failures + 1
    if failures < DEGRADE_AFTER_FAILURES:
        # Below the first rung the source keeps the verdict it earned. The error
        # is still recorded on the row, so the admin page can show "ACTIVE, last
        # attempt failed" — which is what is actually true.
        return current_state

    # A source that has never succeeded is measured from when it was configured,
    # so a permanently broken entry cannot sit in DEGRADED forever on the
    # strength of never having had a success to age out.
    failing_since = last_success_at or created_at
    if failing_since is not None and now - failing_since >= QUARANTINE_AFTER:
        return "QUARANTINED"

    return "DEGRADED"

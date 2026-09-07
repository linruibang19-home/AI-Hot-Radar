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


# A source that has been polled successfully for this long and has still never
# stored a single document is not quiet — it is broken.
NEVER_PRODUCED_AFTER = timedelta(days=3)

#: How many successful polls must have happened in that window before the
#: verdict is fair. A source configured yesterday with a 6-hour interval has not
#: had a real chance yet.
NEVER_PRODUCED_MIN_POLLS = 12

_STALLED = """
    SELECT s.id,
           s.priority,
           count(cr.id) FILTER (WHERE cr.status = 'SUCCESS') AS successes,
           min(cr.started_at) FILTER (WHERE cr.status = 'SUCCESS') AS first_success
      FROM source s
      JOIN crawl_run cr ON cr.source_id = s.id
     WHERE s.configured_enabled
       AND NOT EXISTS (SELECT 1 FROM content_item ci WHERE ci.source_id = s.id)
     GROUP BY s.id, s.priority
    HAVING count(cr.id) FILTER (WHERE cr.status = 'SUCCESS') >= %(min_polls)s
       AND min(cr.started_at) FILTER (WHERE cr.status = 'SUCCESS') <= %(cutoff)s
     ORDER BY s.priority, s.id
"""


def stalled_sources(connection: object, *, now: datetime) -> list[dict[str, object]]:
    """Sources that poll successfully and have never produced a document.

    This is the signal that was missing when `openai-news` — a P0 first-party
    feed — sat at zero items for 37 days. Every conventional check was green:
    `status = SUCCESS`, `HTTP 200`, `consecutive_failures = 0`, empty error log.
    The one number that told the truth, `discovered_count = 0` on every run, was
    indistinguishable from a quiet week and so nothing looked at it.

    **Deliberately narrow.** "No new content lately" would fire on genuinely
    slow publishers and on `github_repo_activity`, where one living document per
    repository is the design rather than a fault. "Polled successfully for days
    and never stored anything" has no honest explanation.
    """
    cutoff = now - NEVER_PRODUCED_AFTER
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(_STALLED, {"min_polls": NEVER_PRODUCED_MIN_POLLS, "cutoff": cutoff})
        rows = cursor.fetchall()

    return [
        {
            "source_id": row[0],
            "priority": row[1],
            "successful_polls": int(row[2]),
            "polling_since": row[3].isoformat() if row[3] else None,
            "days": round((now - row[3]).total_seconds() / 86400, 1) if row[3] else None,
        }
        for row in rows
    ]

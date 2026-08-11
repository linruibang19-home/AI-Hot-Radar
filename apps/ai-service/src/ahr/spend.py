"""A daily ceiling on model spend, enforced before the call (M5 launch gate).

The rate limiter bounds how many questions one caller may ask. It does not bound
what the deployment spends: twenty callers within their quota, or one long
enrichment backlog, reach the same provider bill by a route the limiter never
sees. And the limiter **fails open** by design — a Redis restart removes it — so
it is the wrong thing to be the only defence.

`llm_usage` has recorded real provider-reported tokens since M2, which makes the
ceiling measurable rather than estimated: this counts what was actually billed,
not what a character-count heuristic guessed.

**Tokens rather than money.** Converting to currency needs per-model prices that
drift and that this repository cannot verify; a wrong price makes the guard
either useless or a spurious outage. A token ceiling is exact, and the operator
sets it from whatever price they are actually paying.

**This does not replace a provider-side cap, and must not be described as one.**
It bounds what *this application* spends through `llm_usage`, so it cannot see
the embedding and rerank providers, which are a different account and are not
recorded there. It also cannot stop anything that bypasses this code. The
deployment checklist keeps the provider-side limit as a separate item for
exactly that reason.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 0 disables the guard, which is the default: a limit invented here would either
# be too low for a real deployment or too high to matter, and either teaches the
# operator to ignore it. The deployment checklist is where a number gets chosen.
DEFAULT_DAILY_TOKEN_LIMIT = 0


def daily_token_limit() -> int:
    raw = os.environ.get("LLM_DAILY_TOKEN_LIMIT", str(DEFAULT_DAILY_TOKEN_LIMIT)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("LLM_DAILY_TOKEN_LIMIT is not a number (%r), guard disabled", raw)
        return 0


@dataclass(frozen=True)
class SpendDecision:
    allowed: bool
    used: int
    limit: int

    @property
    def message(self) -> str:
        return (
            f"今日模型用量已达上限（{self.used:,} / {self.limit:,} tokens），"
            "问答暂停到明天。这是为了防止账单失控，不是故障。"
        )


def tokens_used_today(connection: Any) -> int:
    """Provider-reported tokens billed since local midnight.

    Local rather than UTC, matching every other daily boundary in this project —
    the report cutoff and the rate limiter's day both moved to `Asia/Shanghai`
    after UTC midnight put eight hours of Chinese evening into the wrong day.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(sum(prompt_tokens + completion_tokens), 0)
              FROM llm_usage
             WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Shanghai')
                                 AT TIME ZONE 'Asia/Shanghai'
            """
        )
        row = cursor.fetchone()
    return int((row or (0,))[0] or 0)


def check(connection: Any) -> SpendDecision:
    """Whether another model call is within today's ceiling.

    **Fails open**, like the rate limiter and for the same reason: a guard that
    takes the feature down when the database hiccups converts a bounded cost
    problem into an outage. The ceiling protects a bill, not correctness.
    """
    limit = daily_token_limit()
    if limit <= 0:
        return SpendDecision(allowed=True, used=0, limit=0)

    try:
        used = tokens_used_today(connection)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning("spend check failed, allowing: %s", exc)
        return SpendDecision(allowed=True, used=0, limit=limit)

    return SpendDecision(allowed=used < limit, used=used, limit=limit)

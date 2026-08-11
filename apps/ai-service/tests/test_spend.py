"""The daily spend ceiling (M5 launch gate).

The rate limiter bounds one caller. Twenty callers each inside their allowance
reach the same bill, and the limiter fails open on a Redis restart — so it
should not be the only thing between a public endpoint and a provider account.
"""

from __future__ import annotations

import inspect

import pytest

from ahr import spend


class _Cursor:
    def __init__(self, value: object) -> None:
        self.value = value

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = ()) -> None:
        if isinstance(self.value, Exception):
            raise self.value

    def fetchone(self) -> tuple[object]:
        return (self.value,)


class _Connection:
    def __init__(self, value: object) -> None:
        self.value = value

    def cursor(self) -> _Cursor:
        return _Cursor(self.value)


def test_the_guard_is_off_unless_a_number_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A limit invented here is either too low for a real deployment or too high
    to matter, and both teach the operator to ignore it."""
    monkeypatch.delenv("LLM_DAILY_TOKEN_LIMIT", raising=False)
    decision = spend.check(_Connection(999_999_999))

    assert decision.allowed is True
    assert decision.limit == 0


def test_it_stops_once_the_ceiling_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_DAILY_TOKEN_LIMIT", "1000")
    assert spend.check(_Connection(1000)).allowed is False
    assert spend.check(_Connection(1001)).allowed is False
    assert spend.check(_Connection(999)).allowed is True


def test_a_database_hiccup_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same rule as the rate limiter: a guard that takes the feature down when
    the database wobbles converts a bounded cost problem into an outage. The
    ceiling protects a bill, not correctness."""
    monkeypatch.setenv("LLM_DAILY_TOKEN_LIMIT", "1000")
    assert spend.check(_Connection(RuntimeError("connection reset"))).allowed is True


def test_a_malformed_limit_disables_rather_than_crashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DAILY_TOKEN_LIMIT", "两百万")
    assert spend.daily_token_limit() == 0


def test_the_day_boundary_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """UTC midnight puts eight hours of Chinese evening into the wrong day —
    the report cutoff and the rate limiter both moved for this reason."""
    assert "Asia/Shanghai" in inspect.getsource(spend.tokens_used_today)


def test_it_counts_what_the_provider_billed(monkeypatch: pytest.MonkeyPatch) -> None:
    """`llm_usage` records provider-reported tokens, so the ceiling is measured
    rather than estimated from a character-count heuristic."""
    source = inspect.getsource(spend.tokens_used_today)
    assert "llm_usage" in source
    assert "prompt_tokens + completion_tokens" in source


def test_the_message_says_it_is_deliberate() -> None:
    """A reader who hits this should know it is a cost guard, not a fault."""
    message = spend.SpendDecision(allowed=False, used=2_000_000, limit=2_000_000).message
    assert "不是故障" in message


def test_both_ask_endpoints_are_guarded() -> None:
    """The stream path spends exactly as much as the plain one."""
    from ahr.rag import api

    source = inspect.getsource(api)
    assert source.count("_enforce_spend()") >= 2

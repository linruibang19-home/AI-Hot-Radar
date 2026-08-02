"""Recommendation-reason prompt construction.

The reasons are shown on every 精选 card as analysis of the article, so what the
model is actually given matters as much as what it is asked.
"""

from __future__ import annotations

from ahr.processing.recommendation import (
    ELLIPSIS,
    MAX_BODY_CHARS,
    SYSTEM_PROMPT,
    TAIL_SHARE,
    excerpt_for_prompt,
)


def test_short_body_is_passed_through_untouched() -> None:
    body = "短正文" * 10
    assert excerpt_for_prompt(body) == body


def test_body_at_the_budget_is_not_truncated() -> None:
    body = "x" * MAX_BODY_CHARS
    assert excerpt_for_prompt(body) == body


def test_long_body_keeps_the_conclusion() -> None:
    """72% of selected items exceeded the old budget and lost their endings.

    The prompt requires the model to state a limitation, and long articles put
    their caveats last — so head-only truncation removed exactly the material
    that requirement depends on.
    """
    body = "开头段落。" + ("中间填充。" * 4000) + "结论：本方法仅在单一数据集上验证。"
    excerpt = excerpt_for_prompt(body)

    assert "开头段落。" in excerpt
    assert "结论：本方法仅在单一数据集上验证。" in excerpt


def test_the_gap_is_marked() -> None:
    """An unmarked join invites the model to connect two unrelated passages."""
    body = "A" * 3000 + "B" * 9000
    assert ELLIPSIS in excerpt_for_prompt(body)


def test_excerpt_stays_within_budget() -> None:
    body = "字" * 100_000
    excerpt = excerpt_for_prompt(body)
    assert len(excerpt) <= MAX_BODY_CHARS + len(ELLIPSIS)


def test_tail_share_leaves_the_head_dominant() -> None:
    """The opening still carries most releases' substance; the tail is insurance."""
    assert 0 < TAIL_SHARE < 0.5


def test_budget_is_respected_for_a_custom_value() -> None:
    excerpt = excerpt_for_prompt("y" * 5000, budget=100)
    assert len(excerpt) <= 100 + len(ELLIPSIS)


def test_prompt_demands_a_stated_limitation() -> None:
    """Without this the reason is advertising, not analysis (AHR-SPEC-000 §7)."""
    assert "局限" in SYSTEM_PROMPT


def test_prompt_forbids_facts_absent_from_the_body() -> None:
    assert "禁止补充正文没有的信息" in SYSTEM_PROMPT

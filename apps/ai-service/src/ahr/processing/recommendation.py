"""LLM-written recommendation reasons.

The first version of selection produced a reason by naming the top-scoring
factors ("一手/权威来源、正文信息量充足、属于关键变更类型"). Because the factor
ranking is nearly identical for every release note, every card ended up with
the same sentence, which tells a reader nothing.

This module asks the model to judge the specific article: what it concretely
helps with, and what it does not establish. The honest limitation matters —
AHR-SPEC-000 §7 forbids presenting generated text as settled fact, and a reason
that only praises is advertising, not analysis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ahr.processing.llm import LlmClient, LlmUnavailableError, TokenUsage

# v2 changed what the model is shown, not what it is asked: v1 passed only the
# first 4000 characters, which truncated 72% of selected items and cut exactly
# the closing passage the "state a limitation" requirement depends on. Bumping
# the version makes the backfill re-run over reasons written from the old
# excerpt rather than leaving two prompt generations mixed on the same page.
RECOMMENDATION_PROMPT_VERSION = "recommend-v2"

MAX_BODY_CHARS = 6000

# Of the body budget, how much comes from the end of the article.
#
# Taking only the opening truncated 72% of selected items, and it truncated them
# in the worst possible place: a release note leads with its changes, but an
# analysis piece leads with background and states its conclusion — and its
# caveats — at the end. Since the prompt requires a stated limitation, cutting
# the tail removed exactly the material that requirement depends on.
TAIL_SHARE = 0.35

ELLIPSIS = "\n\n……（正文中段略）……\n\n"


def excerpt_for_prompt(body_text: str, *, budget: int = MAX_BODY_CHARS) -> str:
    """Head plus tail, so a long article's conclusion survives truncation.

    The gap is marked, so the model is not led to believe the two halves are
    contiguous and invent a connection between them.
    """
    if len(body_text) <= budget:
        return body_text

    tail_chars = int(budget * TAIL_SHARE)
    head_chars = budget - tail_chars
    return body_text[:head_chars] + ELLIPSIS + body_text[-tail_chars:]


SYSTEM_PROMPT = """你是 AI 行业资深编辑，为「精选」栏目撰写推荐理由。

要求：
1. 只输出推荐理由正文，2-3 句，60-140 字，不要标题、编号、markdown。
2. 必须针对这条内容本身：它具体带来什么变化、对谁有用、解决了什么问题。
3. 必须指出一处局限或待验证之处（例如未公开评测、仅限特定平台、样本有限、尚未生效）。
4. 只能使用正文中的事实，禁止补充正文没有的信息，禁止空泛套话。
5. 不要写「值得关注」「意义重大」这类没有信息量的评价。

反例（禁止这样写）：一手/权威来源、正文信息量充足、属于关键变更类型。
正例：该版本把工具调用从实验特性转为默认开启，对已用该 SDK 的项目意味着可以移除自定义封装；
但发布说明未给出与旧版的性能对比，实际收益仍需自行验证。"""


@dataclass
class RecommendationResult:
    reason: str
    usage: TokenUsage
    model: str


def _clean(text: str) -> str:
    """Strip wrappers models add despite instructions."""
    cleaned = text.strip().strip("`").strip()
    for prefix in ("推荐理由：", "推荐理由:", "理由：", "理由:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned


async def write_reason(
    client: LlmClient,
    *,
    title: str,
    summary: str | None,
    body_text: str,
    source_name: str,
    content_type: str | None,
) -> RecommendationResult:
    """Generate a reason for one item."""
    prompt = (
        f"来源：{source_name}\n"
        f"类型：{content_type or '未分类'}\n"
        f"标题：{title}\n"
        f"{('摘要：' + summary) if summary else ''}\n\n"
        f"正文：\n{excerpt_for_prompt(body_text)}"
    )

    text, usage = await client.summarize(system_prompt=SYSTEM_PROMPT, user_prompt=prompt)
    return RecommendationResult(reason=_clean(text), usage=usage, model=client.model_name)


def _pending_selections(connection: Any, limit: int, force: bool) -> list[tuple[Any, ...]]:
    """Selections still carrying a templated reason, newest first."""
    condition = (
        "TRUE"
        if force
        # Templated reasons are identified by version rather than by matching
        # their text, so a future prompt revision re-runs cleanly.
        else "(sr.reason_version IS NULL OR sr.reason_version <> %(version)s)"
    )
    query = f"""
        SELECT sr.id, ci.id, COALESCE(ci.zh_title, ci.title), ci.summary_zh,
               cr.body_text, s.name, ci.content_type
          FROM selection_record sr
          JOIN content_item ci ON ci.id = sr.content_item_id
          JOIN source s ON s.id = ci.source_id
          LEFT JOIN content_revision cr ON cr.id = ci.current_revision_id
         WHERE sr.withdrawn_at IS NULL
           AND ci.duplicate_of_id IS NULL
           AND {condition}
         ORDER BY sr.selected_for_date DESC, sr.score DESC
         LIMIT %(limit)s
    """
    with connection.cursor() as cursor:
        cursor.execute(query, {"version": RECOMMENDATION_PROMPT_VERSION, "limit": limit})
        return list(cursor.fetchall())


async def backfill_reasons(
    connection: Any, *, limit: int, client: LlmClient, force: bool = False
) -> dict[str, int]:
    """Write LLM reasons for selections that do not have one yet."""
    rows = _pending_selections(connection, limit, force)
    written = 0
    failed = 0
    prompt_tokens = 0
    completion_tokens = 0

    for selection_id, item_id, title, summary, body, source_name, content_type in rows:
        if not body:
            continue
        try:
            result = await write_reason(
                client,
                title=title,
                summary=summary,
                body_text=body,
                source_name=source_name,
                content_type=content_type,
            )
        except LlmUnavailableError:
            # Stop rather than burn through the batch against a down provider;
            # the existing reason stays visible in the meantime.
            failed += 1
            break

        if not result.reason:
            failed += 1
            continue

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE selection_record
                   SET reason = %s, reason_version = %s, reason_model = %s
                 WHERE id = %s
                """,
                (result.reason[:600], RECOMMENDATION_PROMPT_VERSION, result.model, selection_id),
            )
            cursor.execute(
                """
                INSERT INTO llm_usage (
                    id, content_item_id, operation, model, prompt_version,
                    prompt_tokens, completion_tokens, cached_tokens,
                    attempts, succeeded, latency_ms
                ) VALUES (%s, %s, 'recommend', %s, %s, %s, %s, %s, %s, TRUE, %s)
                """,
                (
                    uuid.uuid4(),
                    item_id,
                    result.model,
                    RECOMMENDATION_PROMPT_VERSION,
                    result.usage.prompt_tokens,
                    result.usage.completion_tokens,
                    result.usage.cached_tokens,
                    result.usage.attempts,
                    result.usage.latency_ms,
                ),
            )
        connection.commit()

        written += 1
        prompt_tokens += result.usage.prompt_tokens
        completion_tokens += result.usage.completion_tokens

    return {
        "candidates": len(rows),
        "written": written,
        "failed": failed,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }

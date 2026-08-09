"""Understanding the question with a model instead of six regexes (Phase B-3).

The regex planner is right most of the time and wrong in a way nothing notices.
Measured on ten live questions, three were misclassified — 「Qwen 系列模型的发布顺序
是怎样的？」 fell through to `explainer` because 「发布顺序」 was not in the timeline
pattern, and 「使用 MXFP4 量化的是哪个模型？」 for the same reason on `fact_check`.
Each miss is silent: `query_type` decides whether the time window filters the
channels, which row of the `source_fit` table applies, and whether `temporal_fit`
runs, and none of those raise when the type is wrong.

Adding a phrase to a regex fixes the phrase and not the class. This is the
`self-query` pattern from LlamaIndex, and the reason it is standard: the space of
ways to ask for a timeline is not enumerable.

**The regex planner stays, as the fallback and as the floor.** A planner is on
the critical path of every question, and a provider timeout must not become a
failed answer — so any failure, malformed output or unknown value falls back to
the deterministic planner rather than propagating. That also keeps the offline
evaluation runnable with no provider at all.

**Not enabled by default.** It costs one model round trip per question on a p50
of about 10s, and — more decisively — its accuracy cannot be compared against the
regex planner until the golden set carries `expected_query_type`. Shipping it on
because it is more sophisticated is exactly the move this project's evaluation
discipline exists to prevent. `disagreements()` is the tool for earning that
annotation cheaply: it runs both planners and reports only where they differ, so
a human adjudicates a short list rather than ninety questions.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ahr.processing.llm import LlmClient, LlmUnavailableError
from ahr.rag.planner import (
    DISPLAY_TIMEZONE,
    QUERY_TYPES,
    RetrievalPlan,
    range_from_dates,
)
from ahr.rag.planner import plan as regex_plan

logger = logging.getLogger(__name__)

PLANNER_PROMPT_VERSION = "rag-planner-v1"

SYSTEM_PROMPT = """你是检索计划器。把用户的问题解析成结构化的检索计划。

query_type 六选一：
- recent_updates：问某段时间内发生了什么、有什么新动态
- timeline：问事情的先后顺序、演进过程、发布顺序
- comparison：问两个或多个对象的差别、优劣
- fact_check：问一个具体的事实（数值、型号、是谁、是哪个）
- explainer：问原理、机制、为什么、怎么工作
- recommendation：问该选哪个、值得不值得

time_range 给绝对日期，格式 YYYY-MM-DD：
- 「最近/近期/现在/目前」无跨度 → 从今天往前 7 天
- 「本周/上周/本月/上月/今天/昨天」→ 按字面解析
- 问题不含任何时间语义 → 给 null（解释原理、比较、事实核验通常都是 null）

entities：问题中提到的公司、产品、模型名，原样抄写，没有就给空数组。

只输出 JSON，不要解释：
{"query_type": "...", "time_from": "YYYY-MM-DD"|null,
 "time_to": "YYYY-MM-DD"|null, "entities": ["..."]}"""


@dataclass(frozen=True)
class PlannerOutput:
    query_type: str
    window: tuple[date, date] | None
    entities: tuple[str, ...]


def _parse(raw: str) -> PlannerOutput | None:
    """Read the model's JSON, rejecting anything the pipeline cannot use.

    Returns None rather than a partial plan. A `query_type` outside the six is
    not a near-miss to be coerced — it would silently select the wrong
    `source_fit` row — and the caller has a correct planner to fall back to.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    query_type = parsed.get("query_type")
    if query_type not in QUERY_TYPES:
        return None

    window: tuple[date, date] | None = None
    start, end = parsed.get("time_from"), parsed.get("time_to")
    if isinstance(start, str) and isinstance(end, str):
        try:
            bounds = (date.fromisoformat(start), date.fromisoformat(end))
        except ValueError:
            return None
        if bounds[1] < bounds[0]:
            return None
        window = bounds

    entities = tuple(
        str(name).strip() for name in (parsed.get("entities") or []) if str(name).strip()
    )
    return PlannerOutput(query_type=query_type, window=window, entities=entities)


async def plan_with_llm(
    llm: LlmClient,
    question: str,
    *,
    asked_at: datetime,
) -> tuple[RetrievalPlan, bool]:
    """Plan with the model, falling back to the regex planner on any failure.

    Returns the plan and whether the model produced it, so the caller can record
    which planner a stored answer was built with — an answer replayed from a
    permalink should say how its window was chosen.
    """
    today = asked_at.astimezone(DISPLAY_TIMEZONE).date().isoformat()
    try:
        raw, _usage = await llm.summarize(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=f"今天是 {today}。\n问题：{question}",
        )
    except LlmUnavailableError as exc:
        # A planner outage must cost precision, never the answer.
        logger.warning("llm planner unavailable, using regex plan: %s", exc)
        return regex_plan(question, asked_at=asked_at), False

    parsed = _parse(raw)
    if parsed is None:
        logger.warning("llm planner returned unusable output, using regex plan")
        return regex_plan(question, asked_at=asked_at), False

    # `null` from the model means "no time window", and it has to mean that
    # rather than "fall back to the regex" — otherwise the model can never
    # correct the regex's habit of putting a window on an explainer, which is
    # one of the two things it is here to fix.
    #
    # Dates go through `range_from_dates`, the same conversion the reader's date
    # picker uses, so the two cannot disagree about half-open ends.
    time_range = range_from_dates(*parsed.window) if parsed.window else None

    return (
        RetrievalPlan(
            question=question,
            query_type=parsed.query_type,
            time_range=time_range,
            asked_at=asked_at,
            freshness_required=parsed.query_type in {"recent_updates", "timeline"},
            notes=(f"计划由模型解析（{PLANNER_PROMPT_VERSION}）",),
        ),
        True,
    )


async def disagreements(
    llm: LlmClient,
    questions: list[tuple[str, str, datetime]],
) -> list[dict[str, Any]]:
    """Where the two planners differ, and nothing else.

    The golden set has no `expected_query_type`, so neither planner can be
    scored. Annotating ninety questions to find out is the expensive way; the
    two planners agreeing is weak evidence that both are right, and the
    disagreements are exactly the cases worth a human's judgement.

    Deriving the expectation from either planner would measure nothing — this
    produces *candidates for adjudication*, not answers.
    """
    rows: list[dict[str, Any]] = []
    for qid, question, asked_at in questions:
        baseline = regex_plan(question, asked_at=asked_at)
        proposed, from_model = await plan_with_llm(llm, question, asked_at=asked_at)
        if not from_model:
            continue

        same_type = baseline.query_type == proposed.query_type
        same_window = (baseline.time_range is None) == (proposed.time_range is None)
        if same_type and same_window:
            continue

        rows.append(
            {
                "question_id": qid,
                "question": question,
                "regex_query_type": baseline.query_type,
                "llm_query_type": proposed.query_type,
                "regex_window": baseline.time_range.label if baseline.time_range else None,
                "llm_window": proposed.time_range.label if proposed.time_range else None,
            }
        )
    return rows

"""Daily report generation.

AHR-FEAT-105 requires a report to be built from the curated shortlist rather
than by concatenating every article, to record the versions it was produced
with, and to keep every claim traceable to a source. `report_item` stores that
provenance so the web, email and RSS renderings all read the same facts.

The report degrades rather than fails: without a model it still produces a
grouped, linked digest, because a daily report that vanishes when the LLM is
down is worse than one without a narrative paragraph.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ahr.processing.llm import LlmClient, LlmUnavailableError

REPORT_PROMPT_VERSION = "report-v2"

# Weekly and monthly digests reuse the daily pipeline; only the window and the
# prompt emphasis change, so the rendering and provenance paths stay identical
# and web/email/RSS cannot drift apart (AHR-FEAT-105).
PERIOD_LABELS = {"daily": "日报", "weekly": "周报", "monthly": "月报"}

SECTION_ORDER = [
    ("model_release", "模型发布"),
    ("product_release", "产品发布"),
    ("api_update", "API 与平台更新"),
    ("open_source", "开源项目"),
    ("research", "研究进展"),
    ("security", "安全"),
    ("business", "行业与商业"),
    ("policy", "政策与监管"),
    ("tutorial", "教程与实践"),
    ("opinion", "观点"),
]

SUMMARY_PROMPTS = {
    "daily": """你是 AI 行业日报编辑。根据给定的当日精选条目，写一段中文总述。

要求：
1. 3-5 句，先说当天最重要的变化，再说次要趋势。
2. 只能使用给定条目中的事实，禁止补充任何未提供的信息。
3. 不要罗列全部条目，抓主线。
4. 只输出总述正文，不要标题、不要 markdown、不要编号。""",
    "weekly": """你是 AI 行业周报主编。根据给定的本周精选条目，写一段中文总述。

要求：
1. 4-6 句。周报关注的是**趋势**而非单个事件：哪条主线在推进、哪些厂商在同一方向上动作。
2. 如果多条内容指向同一变化，合并成一句话说清楚，不要重复罗列。
3. 只能使用给定条目中的事实，禁止补充任何未提供的信息。
4. 只输出总述正文，不要标题、不要 markdown、不要编号。""",
    "monthly": """你是 AI 行业月报主编。根据给定的本月精选条目，写一段中文总述。

要求：
1. 5-8 句。月报关注**格局变化**：能力边界推到了哪里、竞争态势有何变化、哪些方向开始收敛或分化。
2. 必须给出至少一个跨条目的归纳判断，而不是事件流水账。
3. 只能使用给定条目中的事实，禁止补充任何未提供的信息，不确定的地方要说明是趋势推测。
4. 只输出总述正文，不要标题、不要 markdown、不要编号。""",
}


@dataclass
class ReportItem:
    item_id: uuid.UUID
    title: str
    summary: str | None
    source_name: str
    canonical_url: str
    content_type: str | None
    score: float


@dataclass
class DailyReport:
    report_date: date
    period_type: str
    period_key: str
    title: str
    summary: str
    body_markdown: str
    items: list[ReportItem]
    model_name: str | None


def _period_range(period: str, key: str) -> tuple[date, date, str]:
    """Return (start, end_inclusive, title_suffix) for a report period.

    Weekly keys are ISO weeks (2026-W31) so the boundary is unambiguous across
    locales; monthly keys are 2026-08.
    """
    if period == "daily":
        day = date.fromisoformat(key)
        return day, day, key
    if period == "weekly":
        year_text, week_text = key.split("-W")
        # ISO weeks so the boundary is unambiguous: week 1 is the one holding
        # the first Thursday, and day 1 is Monday.
        start = date.fromisocalendar(int(year_text), int(week_text), 1)
        return start, start + timedelta(days=6), f"{start.isoformat()} 起当周"
    if period == "monthly":
        year_text, month_text = key.split("-")
        year, month = int(year_text), int(month_text)
        start = date(year, month, 1)
        # First day of the following month, minus one day. Rolling December
        # into January of the next year is the only wrap case.
        next_year = year + 1 if month == 12 else year
        next_month = 1 if month == 12 else month + 1
        end = date(next_year, next_month, 1) - timedelta(days=1)
        return start, end, f"{year} 年 {month} 月"
    raise ValueError(f"unsupported period: {period}")


def _load_selected(connection: Any, start: date, end: date) -> list[ReportItem]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.id,
                   COALESCE(ci.zh_title, ci.title),
                   ci.summary_zh,
                   s.name,
                   ci.canonical_url,
                   ci.content_type,
                   sr.score
              FROM selection_record sr
              JOIN content_item ci ON ci.id = sr.content_item_id
              JOIN source s ON s.id = ci.source_id
             WHERE sr.selected_for_date BETWEEN %s AND %s
               AND sr.withdrawn_at IS NULL
               AND ci.duplicate_of_id IS NULL
             ORDER BY sr.score DESC
            """,
            (start, end),
        )
        rows = cursor.fetchall()

    return [
        ReportItem(
            item_id=uuid.UUID(str(r[0])),
            title=r[1],
            summary=r[2],
            source_name=r[3],
            canonical_url=r[4],
            content_type=r[5],
            score=float(r[6]),
        )
        for r in rows
    ]


def _group_by_section(items: list[ReportItem]) -> list[tuple[str, list[ReportItem]]]:
    buckets: dict[str, list[ReportItem]] = {}
    for item in items:
        buckets.setdefault(item.content_type or "other", []).append(item)

    ordered: list[tuple[str, list[ReportItem]]] = []
    for key, label in SECTION_ORDER:
        if buckets.get(key):
            ordered.append((label, buckets.pop(key)))
    # Anything the taxonomy did not cover still appears, rather than vanishing.
    leftovers = [item for group in buckets.values() for item in group]
    if leftovers:
        ordered.append(("其他", leftovers))
    return ordered


def render_markdown(title: str, summary: str, sections: list[tuple[str, list[ReportItem]]]) -> str:
    lines = [f"# {title}", ""]
    if summary:
        lines += [summary, ""]

    for label, items in sections:
        lines.append(f"## {label}")
        lines.append("")
        for item in items:
            # Every entry links to the publisher, never to a local copy
            # (AHR-SPEC-000 ADR-009).
            lines.append(f"- **[{item.title}]({item.canonical_url})** · {item.source_name}")
            if item.summary:
                lines.append(f"  {item.summary}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("本报告由 AI Hot Radar 自动生成。摘要为 AI 生成内容，事实请以原文为准。")
    return "\n".join(lines)


async def build_report(
    connection: Any, period: str, key: str, *, client: LlmClient | None = None
) -> DailyReport | None:
    """Build a daily, weekly or monthly report, or None when nothing was selected."""
    start, end, label = _period_range(period, key)
    items = _load_selected(connection, start, end)
    if not items:
        return None

    sections = _group_by_section(items)

    summary = ""
    model_name: str | None = None
    if client is not None:
        # A month can hold hundreds of items; sending them all would blow the
        # context and the budget, so the digest is capped and the highest-scoring
        # items come first.
        digest_limit = {"daily": 20, "weekly": 40, "monthly": 60}[period]
        digest = "\n".join(
            f"- [{item.content_type or 'other'}] {item.title}（{item.source_name}）"
            f"{'：' + item.summary[:120] if item.summary else ''}"
            for item in items[:digest_limit]
        )
        try:
            raw, _usage = await client.summarize(
                system_prompt=SUMMARY_PROMPTS[period],
                user_prompt=f"周期：{label}\n\n该周期精选条目：\n{digest}",
            )
            summary = raw.strip()
            model_name = client.model_name
        except LlmUnavailableError:
            # A report without a narrative is still useful; a missing report is not.
            summary = ""

    if not summary:
        summary = f"{label} 共精选 {len(items)} 条内容，覆盖 {len(sections)} 个类别。"

    title = f"AI Hot Radar {PERIOD_LABELS[period]} · {key}"
    return DailyReport(
        report_date=start,
        period_type=period,
        period_key=key,
        title=title,
        summary=summary,
        body_markdown=render_markdown(title, summary, sections),
        items=items,
        model_name=model_name,
    )


def save_report(connection: Any, report: DailyReport) -> uuid.UUID:
    """Persist the report and its provenance."""
    report_id = uuid.uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO report (
                id, period_type, period_key, title, summary, body_markdown,
                status, generated_at, item_count, prompt_version, model_name,
                generation_meta
            ) VALUES (%s, %s, %s, %s, %s, %s, 'DRAFT', now(), %s, %s, %s, %s::jsonb)
            ON CONFLICT (period_type, period_key) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                body_markdown = EXCLUDED.body_markdown,
                generated_at = now(),
                item_count = EXCLUDED.item_count,
                prompt_version = EXCLUDED.prompt_version,
                model_name = EXCLUDED.model_name
            RETURNING id
            """,
            (
                report_id,
                report.period_type,
                report.period_key,
                report.title,
                report.summary,
                report.body_markdown,
                len(report.items),
                REPORT_PROMPT_VERSION,
                report.model_name,
                json.dumps({"generated_at": datetime.now().isoformat()}),
            ),
        )
        report_id = uuid.UUID(str(cursor.fetchone()[0]))

        # Rebuild provenance so a regenerated report cannot keep stale links.
        cursor.execute("DELETE FROM report_item WHERE report_id = %s", (report_id,))
        for position, item in enumerate(report.items):
            cursor.execute(
                """
                INSERT INTO report_item (report_id, content_item_id, position, section)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (report_id, content_item_id) DO NOTHING
                """,
                (report_id, item.item_id, position, item.content_type),
            )

    connection.commit()
    return report_id

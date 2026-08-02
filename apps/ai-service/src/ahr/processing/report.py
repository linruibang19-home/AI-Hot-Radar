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
from datetime import date, datetime
from typing import Any

from ahr.processing.llm import LlmClient, LlmUnavailableError

REPORT_PROMPT_VERSION = "report-v1"

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

SUMMARY_SYSTEM_PROMPT = """你是 AI 行业日报编辑。根据给定的当日精选条目，写一段中文总述。

要求：
1. 3-5 句，先说当天最重要的变化，再说次要趋势。
2. 只能使用给定条目中的事实，禁止补充任何未提供的信息。
3. 不要罗列全部条目，抓主线。
4. 只输出总述正文，不要标题、不要 markdown、不要编号。"""


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
    title: str
    summary: str
    body_markdown: str
    items: list[ReportItem]
    model_name: str | None


def _load_selected(connection: Any, report_date: date) -> list[ReportItem]:
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
             WHERE sr.selected_for_date = %s
               AND sr.withdrawn_at IS NULL
               AND ci.duplicate_of_id IS NULL
             ORDER BY sr.score DESC
            """,
            (report_date,),
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


def render_markdown(
    report_date: date, summary: str, sections: list[tuple[str, list[ReportItem]]]
) -> str:
    lines = [f"# AI Hot Radar 日报 · {report_date.isoformat()}", ""]
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


async def build_daily_report(
    connection: Any, report_date: date, *, client: LlmClient | None = None
) -> DailyReport | None:
    """Build the report for one day, or None when nothing was selected."""
    items = _load_selected(connection, report_date)
    if not items:
        return None

    sections = _group_by_section(items)

    summary = ""
    model_name: str | None = None
    if client is not None:
        digest = "\n".join(
            f"- [{item.content_type or 'other'}] {item.title}（{item.source_name}）"
            f"{'：' + item.summary[:120] if item.summary else ''}"
            for item in items[:20]
        )
        try:
            raw, _usage = await client.summarize(
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                user_prompt=f"日期：{report_date.isoformat()}\n\n当日精选条目：\n{digest}",
            )
            summary = raw.strip()
            model_name = client.model_name
        except LlmUnavailableError:
            # A report without a narrative is still useful; a missing report is not.
            summary = ""

    if not summary:
        summary = (
            f"{report_date.isoformat()} 共精选 {len(items)} 条内容，覆盖 {len(sections)} 个类别。"
        )

    return DailyReport(
        report_date=report_date,
        title=f"AI Hot Radar 日报 · {report_date.isoformat()}",
        summary=summary,
        body_markdown=render_markdown(report_date, summary, sections),
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
            ) VALUES (%s, 'daily', %s, %s, %s, %s, 'DRAFT', now(), %s, %s, %s, %s::jsonb)
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
                report.report_date.isoformat(),
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

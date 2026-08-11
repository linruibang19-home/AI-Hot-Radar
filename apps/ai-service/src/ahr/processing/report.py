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
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ahr.processing.llm import LlmClient, LlmUnavailableError

REPORT_PROMPT_VERSION = "report-v3"

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
4. summary 字段只写总述正文，不要标题、markdown 或编号。""",
    "weekly": """你是 AI 行业周报主编。根据给定的本周精选条目，写一段中文总述。

要求：
1. 4-6 句。周报关注的是**趋势**而非单个事件：哪条主线在推进、哪些厂商在同一方向上动作。
2. 如果多条内容指向同一变化，合并成一句话说清楚，不要重复罗列。
3. 只能使用给定条目中的事实，禁止补充任何未提供的信息。
4. summary 字段只写总述正文，不要标题、markdown 或编号。""",
    "monthly": """你是 AI 行业月报主编。根据给定的本月精选条目，写一段中文总述。

要求：
1. 5-8 句。月报关注**格局变化**：能力边界推到了哪里、竞争态势有何变化、哪些方向开始收敛或分化。
2. 必须给出至少一个跨条目的归纳判断，而不是事件流水账。
3. 只能使用给定条目中的事实，禁止补充任何未提供的信息，不确定的地方要说明是趋势推测。
4. summary 字段只写总述正文，不要标题、markdown 或编号。""",
}


class ReportSummaryOutput(BaseModel):
    """The only model-authored field in a report; unknown output is rejected."""

    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=1200)


@dataclass
class ReportItem:
    item_id: uuid.UUID
    title: str
    summary: str | None
    source_name: str
    canonical_url: str
    content_type: str | None
    score: float
    # M3: when several selected articles describe one event, the report shows
    # the event once and says how many outlets carried it, rather than listing
    # the same story three times under three headlines.
    story_slug: str | None = None
    independent_sources: int = 1


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


@dataclass(frozen=True)
class PublicationDecision:
    status: str
    reasons: tuple[str, ...]


MIN_PUBLISHED_ITEMS = {"daily": 5, "weekly": 5, "monthly": 10}


def assess_publication(period: str, summary: str, items: list[ReportItem]) -> PublicationDecision:
    """Deterministic report-output gate locked by ADR-0025.

    This gate never reaches back into ingestion, selection or RAG. It only
    decides whether this report edition is safe to expose and formally send.
    """
    reasons: list[str] = []
    minimum = MIN_PUBLISHED_ITEMS.get(period)
    if minimum is None:
        reasons.append("unsupported_period")
    elif len(items) < minimum:
        reasons.append(f"too_few_items:{len(items)}<{minimum}")
    if not summary.strip():
        reasons.append("missing_summary")

    for item in items:
        parsed = urlparse(item.canonical_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            reasons.append(f"invalid_canonical_url:{item.item_id}")
        if not item.title.strip() or not item.source_name.strip():
            reasons.append(f"missing_identity:{item.item_id}")
        if not item.story_slug:
            reasons.append(f"missing_story:{item.item_id}")

    return PublicationDecision(
        status="REVIEW_REQUIRED" if reasons else "PUBLISHED",
        reasons=tuple(reasons),
    )


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
                   sr.score,
                   st.slug,
                   COALESCE(st.independent_source_count, 1)
              FROM selection_record sr
              JOIN content_item ci ON ci.id = sr.content_item_id
              JOIN source s ON s.id = ci.source_id
              LEFT JOIN story st ON st.id = ci.story_id
             WHERE sr.selected_for_date BETWEEN %s AND %s
               AND sr.withdrawn_at IS NULL
               AND ci.duplicate_of_id IS NULL
             ORDER BY sr.score DESC
            """,
            (start, end),
        )
        rows = cursor.fetchall()

    items = [
        ReportItem(
            item_id=uuid.UUID(str(r[0])),
            title=r[1],
            summary=r[2],
            source_name=r[3],
            canonical_url=r[4],
            content_type=r[5],
            score=float(r[6]),
            story_slug=r[7],
            independent_sources=int(r[8] or 1),
        )
        for r in rows
    ]
    return collapse_by_story(items)


def collapse_by_story(items: list[ReportItem]) -> list[ReportItem]:
    """Keep one entry per event (AHR-DATA-300 §8: report is built from Stories).

    Rows arrive ordered by selection score, so the first item seen for a story
    is its highest-scoring article — which is the one worth linking. Items with
    no story are passed through untouched; clustering only covers a recent
    window, so older selections legitimately have none.
    """
    seen: set[str] = set()
    collapsed: list[ReportItem] = []

    for item in items:
        if item.story_slug is not None:
            if item.story_slug in seen:
                continue
            seen.add(item.story_slug)
        collapsed.append(item)

    return collapsed


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
            corroboration = (
                f" · 另有 {item.independent_sources - 1} 家信源报道"
                if item.independent_sources > 1
                else ""
            )
            lines.append(
                f"- **[{item.title}]({item.canonical_url})** · {item.source_name}{corroboration}"
            )
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
                system_prompt=(
                    SUMMARY_PROMPTS[period]
                    + '\n5. 严格输出 JSON：{"summary":"总述正文"}，不得增加其他字段。'
                ),
                user_prompt=f"周期：{label}\n\n该周期精选条目：\n{digest}",
                json_mode=True,
            )
            summary = ReportSummaryOutput.model_validate_json(raw).summary.strip()
            model_name = client.model_name
        except (LlmUnavailableError, ValidationError, ValueError):
            # Invalid model output is untrusted. A deterministic digest is still
            # useful; a missing report or unvalidated narrative is not.
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
    decision = assess_publication(report.period_type, report.summary, report.items)
    gate_meta = {
        "status": decision.status,
        "reasons": list(decision.reasons),
        "checkedAt": datetime.now().isoformat(),
        "version": "report-publication-v1",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO report (
                id, period_type, period_key, title, summary, body_markdown,
                status, generated_at, published_at, item_count, prompt_version, model_name,
                generation_meta
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, now(),
                CASE WHEN %s = 'PUBLISHED' THEN now() ELSE NULL END,
                %s, %s, %s, %s::jsonb
            )
            ON CONFLICT (period_type, period_key) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                body_markdown = EXCLUDED.body_markdown,
                generated_at = now(),
                item_count = EXCLUDED.item_count,
                prompt_version = EXCLUDED.prompt_version,
                model_name = EXCLUDED.model_name,
                generation_meta = EXCLUDED.generation_meta,
                status = CASE
                    WHEN report.status = 'WITHDRAWN' THEN report.status
                    ELSE EXCLUDED.status
                END,
                published_at = CASE
                    WHEN report.status = 'WITHDRAWN' THEN report.published_at
                    WHEN EXCLUDED.status = 'PUBLISHED' THEN now()
                    ELSE NULL
                END
            RETURNING id
            """,
            (
                report_id,
                report.period_type,
                report.period_key,
                report.title,
                report.summary,
                report.body_markdown,
                decision.status,
                decision.status,
                len(report.items),
                REPORT_PROMPT_VERSION,
                report.model_name,
                json.dumps(
                    {
                        "generated_at": datetime.now().isoformat(),
                        "publicationGate": gate_meta,
                    }
                ),
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


def promote_stored_drafts(connection: Any) -> dict[str, int]:
    """Evaluate historical DRAFT rows with the same gate used for new reports.

    The public API switches to PUBLISHED-only. Running this before refreshing
    current periods prevents a correct historical archive from disappearing,
    while malformed rows move to REVIEW_REQUIRED instead of being waved through.
    WITHDRAWN is intentionally absent from the query: an operator hold wins.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT r.id, r.period_type, r.summary,
                   ci.id, COALESCE(ci.zh_title, ci.title), ci.summary_zh,
                   s.name, ci.canonical_url, ci.content_type, 0.0,
                   st.slug, COALESCE(st.independent_source_count, 1)
              FROM report r
              LEFT JOIN report_item ri ON ri.report_id = r.id
              LEFT JOIN content_item ci ON ci.id = ri.content_item_id
              LEFT JOIN source s ON s.id = ci.source_id
              LEFT JOIN story st ON st.id = ci.story_id
             WHERE r.status = 'DRAFT'
             ORDER BY r.id, ri.position
            """
        )
        rows = cursor.fetchall()

    reports: dict[uuid.UUID, tuple[str, str, list[ReportItem]]] = {}
    for row in rows:
        report_id = uuid.UUID(str(row[0]))
        period = str(row[1])
        summary = str(row[2] or "")
        reports.setdefault(report_id, (period, summary, []))
        if row[3] is None:
            continue
        reports[report_id][2].append(
            ReportItem(
                item_id=uuid.UUID(str(row[3])),
                title=str(row[4] or ""),
                summary=row[5],
                source_name=str(row[6] or ""),
                canonical_url=str(row[7] or ""),
                content_type=row[8],
                score=float(row[9] or 0),
                story_slug=row[10],
                independent_sources=int(row[11] or 1),
            )
        )

    counts = {"published": 0, "review_required": 0}
    with connection.cursor() as cursor:
        for report_id, (period, summary, items) in reports.items():
            decision = assess_publication(period, summary, items)
            gate_meta = json.dumps(
                {
                    "status": decision.status,
                    "reasons": list(decision.reasons),
                    "checkedAt": datetime.now().isoformat(),
                    "version": "report-publication-v1",
                    "historicalBackfill": True,
                }
            )
            cursor.execute(
                """
                UPDATE report
                   SET status = %s,
                       published_at = CASE WHEN %s = 'PUBLISHED' THEN now() ELSE NULL END,
                       generation_meta = jsonb_set(
                           COALESCE(generation_meta, '{}'::jsonb),
                           '{publicationGate}', %s::jsonb, true
                       )
                 WHERE id = %s AND status = 'DRAFT'
                """,
                (decision.status, decision.status, gate_meta, report_id),
            )
            counts["published" if decision.status == "PUBLISHED" else "review_required"] += 1
    connection.commit()
    return counts

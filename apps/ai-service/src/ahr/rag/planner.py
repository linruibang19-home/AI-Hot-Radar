"""Query planning: turn a question into a frozen RetrievalPlan.

AHR-RAG-400 §3 makes the plan an immutable execution contract — downstream
nodes may record a degradation but may not change what was asked.

Time resolution is the part that earns its keep. The B1 baseline measured
`recent_updates` as the weakest category by a wide margin (Recall@10 0.619,
MRR 0.468, with the first relevant document as far down as rank 17) for one
reason: **a dense vector carries no time**. "最近" contributes almost nothing to
an embedding, so the search degrades into "anything about this entity" and
returns articles from months ago. Resolving the phrase into an absolute range
is what makes the filter possible at all.

The timezone is not incidental either. Rendering the whole site in UTC once put
every afternoon story under the previous morning; the same mistake in a time
window would silently return the wrong days.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")

# AHR-RAG-400 §3 defaults.
RECENT_DAYS = 7
UNSPECIFIED_DAYS = 30

QueryType = str

QUERY_TYPES = (
    "recent_updates",
    "timeline",
    "comparison",
    "fact_check",
    "explainer",
    "recommendation",
)


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime
    basis: str = "either"
    explicit: bool = False
    label: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "basis": self.basis,
            "timezone": str(DISPLAY_TIMEZONE),
            "explicit": self.explicit,
            "label": self.label,
        }


@dataclass(frozen=True)
class RetrievalPlan:
    """Frozen after planning. Downstream may log degradation, not rewrite this."""

    question: str
    query_type: QueryType
    time_range: TimeRange | None
    asked_at: datetime
    freshness_required: bool = False
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "query_type": self.query_type,
            "time_range": self.time_range.as_dict() if self.time_range else None,
            "asked_at": self.asked_at.isoformat(),
            "freshness_required": self.freshness_required,
            "notes": list(self.notes),
        }


# Ordered: the first match wins, so specific phrases precede general ones.
# "上周" has to be tested before "周" or it resolves to the current week.
_EXPLICIT_WINDOWS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"今天|今日|today"), "today"),
    (re.compile(r"昨天|昨日|yesterday"), "yesterday"),
    (re.compile(r"上周|上个星期|last week"), "last_week"),
    (re.compile(r"本周|这周|这个星期|this week"), "this_week"),
    (re.compile(r"上个?月|last month"), "last_month"),
    (re.compile(r"本月|这个月|this month"), "this_month"),
)

_NUMBERED_DAYS = re.compile(r"(?:过去|近|最近|last|past)\s*(\d{1,3})\s*(?:天|日|days?)")
_NUMBERED_WEEKS = re.compile(r"(?:过去|近|最近|last|past)\s*(\d{1,2})\s*(?:周|星期|weeks?)")
_RECENT = re.compile(r"最近|近期|这几天|recent|lately")

_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], QueryType], ...] = (
    (re.compile(r"时间线|先后|一步步|怎么发展|演进|从.*到.*发生|timeline"), "timeline"),
    (re.compile(r"相比|对比|区别|差距|哪个更|和.*比|vs\.?|versus"), "comparison"),
    (re.compile(r"为什么|怎么(实现|做到|工作|运作)|原理|是什么意思|如何实现"), "explainer"),
    (re.compile(r"最近|近期|本周|今天|昨天|这几天|有哪些新|新动作|更新了"), "recent_updates"),
    (re.compile(r"是多少|叫什么|几个|是谁|多少参数|真的吗|是否|确认"), "fact_check"),
    (re.compile(r"推荐|值得|该用|选哪个"), "recommendation"),
)


def _day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    local = moment.astimezone(DISPLAY_TIMEZONE)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def resolve_time_range(question: str, asked_at: datetime) -> TimeRange | None:
    """Absolute range for the question's time expression, in the display timezone.

    Returns None when the question carries no time sense at all — an explainer
    about how an architecture works should not be restricted to last week.
    """
    local_now = asked_at.astimezone(DISPLAY_TIMEZONE)

    for pattern, kind in _EXPLICIT_WINDOWS:
        if not pattern.search(question):
            continue
        if kind == "today":
            start, end = _day_bounds(local_now)
            return TimeRange(start, end, explicit=True, label="今天")
        if kind == "yesterday":
            start, end = _day_bounds(local_now - timedelta(days=1))
            return TimeRange(start, end, explicit=True, label="昨天")
        if kind in {"this_week", "last_week"}:
            midnight, _ = _day_bounds(local_now)
            week_start = midnight - timedelta(days=midnight.weekday())
            if kind == "last_week":
                return TimeRange(
                    week_start - timedelta(days=7), week_start, explicit=True, label="上周"
                )
            return TimeRange(
                week_start, week_start + timedelta(days=7), explicit=True, label="本周"
            )
        if kind in {"this_month", "last_month"}:
            midnight, _ = _day_bounds(local_now)
            month_start = midnight.replace(day=1)
            if kind == "last_month":
                previous_end = month_start
                previous_start = (month_start - timedelta(days=1)).replace(day=1)
                return TimeRange(previous_start, previous_end, explicit=True, label="上个月")
            next_month = (month_start + timedelta(days=32)).replace(day=1)
            return TimeRange(month_start, next_month, explicit=True, label="本月")

    if match := _NUMBERED_WEEKS.search(question):
        weeks = int(match.group(1))
        return TimeRange(
            local_now - timedelta(weeks=weeks), local_now, explicit=True, label=f"最近 {weeks} 周"
        )

    if match := _NUMBERED_DAYS.search(question):
        days = int(match.group(1))
        return TimeRange(
            local_now - timedelta(days=days), local_now, explicit=True, label=f"最近 {days} 天"
        )

    if _RECENT.search(question):
        # §3: "最近" without a span means seven days, and the answer must say so.
        # The window is left implicit so the generator knows to state it.
        return TimeRange(
            local_now - timedelta(days=RECENT_DAYS),
            local_now,
            explicit=False,
            label=f"最近 {RECENT_DAYS} 天",
        )

    return None


def classify(question: str) -> QueryType:
    for pattern, query_type in _TYPE_PATTERNS:
        if pattern.search(question):
            return query_type
    return "explainer"


def plan(question: str, *, asked_at: datetime | None = None) -> RetrievalPlan:
    moment = asked_at or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("asked_at must be timezone-aware")

    query_type = classify(question)
    time_range = resolve_time_range(question, moment)

    notes: list[str] = []
    if time_range and not time_range.explicit:
        notes.append(f"未给出时间跨度，按默认 {RECENT_DAYS} 天检索")
    if query_type == "recent_updates" and time_range is None:
        # "发生了什么" with no time word at all: §3 says 30 days.
        time_range = TimeRange(
            moment.astimezone(DISPLAY_TIMEZONE) - timedelta(days=UNSPECIFIED_DAYS),
            moment.astimezone(DISPLAY_TIMEZONE),
            explicit=False,
            label=f"最近 {UNSPECIFIED_DAYS} 天",
        )
        notes.append(f"问题未含时间词，按默认 {UNSPECIFIED_DAYS} 天检索")

    return RetrievalPlan(
        question=question,
        query_type=query_type,
        time_range=time_range,
        asked_at=moment,
        freshness_required=query_type in {"recent_updates", "timeline"},
        notes=tuple(notes),
    )

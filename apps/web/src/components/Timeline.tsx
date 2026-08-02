import type { ReactNode } from "react";

/**
 * Collapsible day section.
 *
 * Built on <details>/<summary> rather than React state: the pages are
 * server-rendered, so a state-based accordion would need the whole feed to
 * become a client component. The native element also gives keyboard operation
 * and the correct expanded/collapsed announcement for free.
 */

const WEEKDAYS = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];

export function formatDayLabel(day: string): { date: string; weekday: string } {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) {
    return { date: day, weekday: "" };
  }
  return {
    date: `${parsed.getUTCMonth() + 1}月${parsed.getUTCDate()}日`,
    weekday: WEEKDAYS[parsed.getUTCDay()],
  };
}

export function TimelineDay({
  day,
  count,
  defaultOpen,
  children,
}: {
  day: string;
  count: number;
  defaultOpen: boolean;
  children: ReactNode;
}) {
  const { date, weekday } = formatDayLabel(day);

  return (
    <details className="tl-day" open={defaultOpen}>
      <summary className="tl-summary">
        <svg
          className="tl-chevron"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="9 6 15 12 9 18" />
        </svg>
        <span className="tl-date">{date}</span>
        <span className="tl-weekday">
          {weekday}
          {weekday && " · "}
          {count} 条
        </span>
      </summary>
      <div className="tl-body">{children}</div>
    </details>
  );
}

/** One row: a time gutter with a marker, and the card beside it. */
export function TimelineRow({
  time,
  children,
}: {
  time: string;
  children: ReactNode;
}) {
  return (
    <div className="tl-row">
      <div className="tl-gutter">
        <time className="tl-time">{time}</time>
        <span className="tl-dot" aria-hidden="true" />
      </div>
      <div className="tl-content">{children}</div>
    </div>
  );
}

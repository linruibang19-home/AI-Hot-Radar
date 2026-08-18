/**
 * Date and time formatting, in the site's display timezone.
 *
 * Every timestamp used to be rendered by slicing the ISO string
 * (`value.slice(11, 16)`), which prints the UTC clock. For a China-facing site
 * that is eight hours wrong all day: an article published at 16:25 Beijing time
 * showed as "08:25", so an afternoon of news read as though nothing had arrived
 * since morning. Near midnight it also grouped items under the wrong date.
 *
 * The zone is fixed rather than taken from the browser. These pages are
 * server-rendered, so a browser-local format would either mismatch on hydration
 * or force the whole feed to be client-rendered. A named IANA zone also handles
 * DST correctly for zones that have it, which a fixed offset would not.
 */

export const DISPLAY_TIMEZONE = process.env.DISPLAY_TIMEZONE ?? "Asia/Shanghai";

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function parse(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * The parts of a timestamp as seen in the display timezone.
 *
 * `Intl` is the only correct way to do this: manually adding an offset breaks
 * across DST boundaries and gets the date wrong on the days that matter most.
 */
function partsIn(date: Date): Record<string, string> {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: DISPLAY_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    weekday: "short",
  });

  const parts: Record<string, string> = {};
  for (const part of formatter.formatToParts(date)) {
    parts[part.type] = part.value;
  }
  return parts;
}

/** "HH:MM" in the display timezone, or a placeholder. */
export function formatTime(value?: string | null): string {
  const date = parse(value);
  if (!date) return "--:--";
  const parts = partsIn(date);
  // Intl renders midnight as "24" in some environments; normalise it.
  const hour = parts.hour === "24" ? "00" : parts.hour;
  return `${hour}:${parts.minute}`;
}

/**
 * Timeline label that respects the precision provided by the publisher.
 *
 * arXiv RSS publishes a daily batch timestamp, not a paper-level minute.  The
 * stored instant remains useful for ordering, but rendering its Shanghai
 * conversion as "12:00" falsely implies all papers were individually released
 * at noon.
 */
export function formatPublicationTime(
  sourceId: string,
  publishedAt?: string | null,
  observedAt?: string | null,
): string {
  if (sourceId.startsWith("arxiv-")) return "当日发布";
  return formatTime(publishedAt ?? observedAt);
}

/** "YYYY-MM-DD" in the display timezone — the key the feed groups by. */
export function dayKey(value?: string | null): string | null {
  const date = parse(value);
  if (!date) return null;
  const parts = partsIn(date);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/** "8月3日" for a YYYY-MM-DD key that is already in the display timezone. */
export function formatDayLabel(key: string): string {
  const [, month, day] = key.split("-");
  if (!month || !day) return key;
  return `${Number(month)}月${Number(day)}日`;
}

/**
 * "2026年8月19日 周三" — the home page heading.
 *
 * Lived in `app/page.tsx` and rebuilt the weekday by hand:
 * `` `…日星期${formatWeekday(key).slice(2)}` ``. That was written when the table
 * held "星期三"; once it was shortened to "周三" the slice removed the whole word
 * and the heading read "…8月19日星期" with nothing after it. A caller that
 * restates another module's format has no way to notice the format changing, so
 * the function belongs next to the table it depends on.
 */
export function formatToday(now: Date = new Date()): string {
  const key = dayKey(now.toISOString()) ?? "";
  const [year, month, day] = key.split("-");
  return `${year}年${Number(month)}月${Number(day)}日 ${formatWeekday(key)}`;
}

/** "周一" for a YYYY-MM-DD key. */
export function formatWeekday(key: string): string {
  // Parsed as UTC midnight and read back in UTC: the key already carries the
  // display-timezone date, so converting it again would shift it back.
  const date = new Date(`${key}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return "";
  return WEEKDAYS[date.getUTCDay()];
}

/** "2026-08-03 17:12" in the display timezone. */
export function formatDateTime(value?: string | null): string {
  const date = parse(value);
  if (!date) return "—";
  const parts = partsIn(date);
  const hour = parts.hour === "24" ? "00" : parts.hour;
  return `${parts.year}-${parts.month}-${parts.day} ${hour}:${parts.minute}`;
}

/** "08-03 17:12" — compact form for dense tables. */
export function formatShortDateTime(value?: string | null): string {
  const date = parse(value);
  if (!date) return "—";
  const parts = partsIn(date);
  const hour = parts.hour === "24" ? "00" : parts.hour;
  return `${parts.month}-${parts.day} ${hour}:${parts.minute}`;
}

/** "2026-08-03" in the display timezone. */
export function formatDate(value?: string | null): string {
  return dayKey(value) ?? "时间未知";
}

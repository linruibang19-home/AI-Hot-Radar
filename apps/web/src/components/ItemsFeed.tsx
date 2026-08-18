"use client";

import { useCallback, useState } from "react";

import { ItemCard } from "@/components/ItemCard";
import { TimelineRow } from "@/components/Timeline";
import { dayHeading } from "@/lib/datetime";
import { formatTime } from "@/lib/datetime";
import { appendItems, type ContentItem, type DayBucket, type ItemPage } from "@/lib/api";

/**
 * The full feed, organised by publication date.
 *
 * Three defects led here, and all three came from paginating by item count
 * while the page is read by date:
 *
 * 1. "Load more" was a link to `/items?cursor=…`, which **replaced** the list.
 * 2. A collapsed `<details>` is uncontrolled — React never restores `open`, so
 *    appended items landed in a section that stayed shut.
 * 3. A single day held close to 200 items, so reaching the previous date took
 *    eight clicks that each looked like nothing had happened.
 *
 * Now every date the corpus contains is rendered at once from a cheap GROUP BY,
 * and a day's items are fetched the first time it is opened. There is no
 * "load more" left to misfire: the whole timeline is visible immediately, and
 * nothing is downloaded until a reader asks for it.
 */

const OPEN_BY_DEFAULT = 3;

interface Props {
  days: DayBucket[];
  initialDay?: string;
  initialItems: ContentItem[];
  /**
   * Whether the server-rendered page covered the whole day.
   *
   * The API caps a page at 50 and the busiest day holds far more, so the first
   * paint is often a partial day. Seeding it as `loaded` told the client the
   * day was complete and it never fetched the rest: the header read "89 条"
   * above 50 rows.
   */
  initialComplete?: boolean;
  query?: string;
  category?: string;
}

type DayState = {
  items: ContentItem[];
  loading: boolean;
  failed: boolean;
  loaded: boolean;
};

export function ItemsFeed({
  days,
  initialDay,
  initialItems,
  initialComplete,
  query,
  category,
}: Props) {
  const [state, setState] = useState<Record<string, DayState>>(() =>
    initialDay
      ? {
          [initialDay]: {
            items: initialItems,
            loading: false,
            failed: false,
            loaded: initialComplete ?? false,
          },
        }
      : {},
  );

  const loadDay = useCallback(
    async (day: string) => {
      // Already loaded, or in flight. Opening and closing a day repeatedly must
      // not re-fetch it.
      if (state[day]?.loaded || state[day]?.loading) return;

      setState((current) => ({
        ...current,
        [day]: { items: current[day]?.items ?? [], loading: true, failed: false, loaded: false },
      }));

      try {
        let cursor: string | null = null;
        let collected: ContentItem[] = [];

        // A day is bounded — the busiest so far held 193 items — so it is
        // fetched whole rather than paged in the UI. The API caps a page at 50.
        for (let page = 0; page < 8; page += 1) {
          const params = new URLSearchParams({ day, limit: "50" });
          if (cursor) params.set("cursor", cursor);
          if (query) params.set("q", query);
          if (category && category !== "all") params.set("contentType", category);

          const response = await fetch(`/api/items?${params}`, { cache: "no-store" });
          if (!response.ok) throw new Error(`items responded ${response.status}`);
          const body = (await response.json()) as ItemPage;

          collected = appendItems(collected, body.data);
          cursor = body.page.nextCursor;
          if (!cursor) break;
        }

        setState((current) => ({
          ...current,
          [day]: { items: collected, loading: false, failed: false, loaded: true },
        }));
      } catch (error) {
        console.error(`loading ${day} failed:`, error);
        setState((current) => ({
          ...current,
          [day]: { items: current[day]?.items ?? [], loading: false, failed: true, loaded: false },
        }));
      }
    },
    [state, query, category],
  );

  if (days.length === 0) {
    return <div className="empty">没有匹配的内容。</div>;
  }

  return (
    <>
      {days.map((bucket, index) => {
        const open = index < OPEN_BY_DEFAULT;
        const day = state[bucket.day];
        const { date, weekday } = dayHeading(bucket.day);

        return (
          <details
            key={bucket.day}
            className="tl-day"
            open={open}
            onToggle={(event) => {
              if (event.currentTarget.open) void loadDay(bucket.day);
            }}
            // The first days are open on mount, so their contents must be
            // requested without waiting for a toggle that will never fire.
            ref={
              open
                ? (node) => {
                    if (node) void loadDay(bucket.day);
                  }
                : undefined
            }
          >
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
                {bucket.total} 条
              </span>
            </summary>

            <div className="tl-body">
              {day?.loading && <p className="filter-note">加载中…</p>}
              {day?.failed && (
                <p className="filter-note" role="alert">
                  加载失败，收起后重新展开可重试。
                </p>
              )}
              {day?.items.map((item) => (
                <TimelineRow
                  key={item.id}
                  time={formatTime(item.publishedAt ?? item.observedAt)}
                >
                  <ItemCard item={item} />
                </TimelineRow>
              ))}
            </div>
          </details>
        );
      })}
    </>
  );
}

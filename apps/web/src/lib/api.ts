/**
 * Server-side client for core-api.
 *
 * The browser never talks to core-api directly (AHR-ARCH-200 §3: the web tier
 * must not reach past the API), so these run during SSR only.
 */

import { dayKey } from "@/lib/datetime";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://core-api:8080";

export interface SourceRef {
  id: string;
  name: string;
  tier: string;
  organization?: string;
}

export interface ContentItem {
  id: string;
  title: string;
  zhTitle?: string;
  summary?: string;
  excerpt?: string;
  canonicalUrl: string;
  publishedAt?: string;
  observedAt: string;
  contentType?: string;
  qualityScore?: number;
  hotScore?: number;
  independentSources?: number;
  source: SourceRef;
}

export interface ItemPage {
  data: ContentItem[];
  page: { nextCursor: string | null; hasMore: boolean };
}

export interface Stats {
  items: number;
  enriched: number;
  activeSources: number;
  chunks: number;
}

export interface SelectedItem {
  item: ContentItem;
  selectedFor: string;
  score: number;
  reason: string;
}

export interface TopicSummary {
  slug: string;
  name: string;
  total: number;
}

export interface TopicRef {
  slug: string;
  name: string;
  confidence?: number;
}

const EMPTY_PAGE: ItemPage = { data: [], page: { nextCursor: null, hasMore: false } };

/**
 * The web tier's own admin credential — read-only by role.
 *
 * Server-side only, so it never reaches a browser. The role matters more than
 * the secrecy: this container renders the source console and never mutates, so
 * the token it holds is one that *cannot* mutate. Compromising the web tier
 * therefore does not hand over the ingestion pipeline.
 */
const ADMIN_VIEWER_TOKEN = process.env.AHR_ADMIN_VIEWER_TOKEN ?? "";

async function getJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      headers:
        path.startsWith("/api/v1/admin/") && ADMIN_VIEWER_TOKEN
          ? { Authorization: `Bearer ${ADMIN_VIEWER_TOKEN}` }
          : {},
      // Deliberately uncached at this layer.
      //
      // `next: { revalidate: 60 }` was serving stale responses long past the
      // window — after the pipeline rewrote every recommendation reason, the
      // site kept rendering the old text until the container was restarted.
      // Two caches over the same data meant the outer one could not be
      // invalidated by anything the backend did.
      //
      // core-api already caches these reads in Redis with explicit TTLs
      // (selected 5min / topics 10min / stats 2min), so one layer is enough and
      // flushing Redis is now sufficient to refresh the site.
      cache: "no-store",
    });
    if (!response.ok) {
      console.error(`core-api ${path} responded ${response.status}`);
      return fallback;
    }
    return (await response.json()) as T;
  } catch (error) {
    // A degraded API must render an empty state, not a 500 page.
    console.error(`core-api ${path} unreachable:`, error);
    return fallback;
  }
}

export function fetchItems(params: {
  limit?: number;
  cursor?: string;
  q?: string;
  contentType?: string;
  day?: string;
} = {}): Promise<ItemPage> {
  const query = new URLSearchParams();
  if (params.limit) query.set("limit", String(params.limit));
  if (params.cursor) query.set("cursor", params.cursor);
  if (params.q) query.set("q", params.q);
  if (params.contentType) query.set("contentType", params.contentType);
  if (params.day) query.set("day", params.day);

  const suffix = query.toString() ? `?${query}` : "";
  return getJson<ItemPage>(`/api/v1/items${suffix}`, EMPTY_PAGE);
}

export interface DayBucket {
  day: string;
  total: number;
}

/** Every publication date with its item count, newest first. */
export function fetchItemDays(params: { q?: string; contentType?: string } = {}): Promise<
  DayBucket[]
> {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.contentType) query.set("contentType", params.contentType);
  const suffix = query.toString() ? `?${query}` : "";
  return getJson<DayBucket[]>(`/api/v1/items/days${suffix}`, []);
}

export async function fetchItem(id: string): Promise<ContentItem | null> {
  return getJson<ContentItem | null>(`/api/v1/items/${id}`, null);
}

export function fetchStats(): Promise<Stats> {
  return getJson<Stats>("/api/v1/stats", {
    items: 0,
    enriched: 0,
    activeSources: 0,
    chunks: 0,
  });
}

export type SelectionSort = "curated" | "latest" | "heat";

export function fetchSelected(
  days = 7,
  limit = 40,
  options: { contentType?: string; sort?: SelectionSort } = {},
): Promise<SelectedItem[]> {
  const query = new URLSearchParams({ days: String(days), limit: String(limit) });
  if (options.contentType && options.contentType !== "all") {
    query.set("contentType", options.contentType);
  }
  if (options.sort) query.set("sort", options.sort);
  return getJson<SelectedItem[]>(`/api/v1/selected?${query}`, []);
}

export interface HotItem {
  id: string;
  title: string;
  heat: number;
  independentSources: number;
  contentType?: string;
  sourceName: string;
}

export function fetchHot(limit = 10): Promise<HotItem[]> {
  return getJson<HotItem[]>(`/api/v1/hot?limit=${limit}`, []);
}

export interface StorySummary {
  id: string;
  slug: string;
  title: string;
  occurredAt?: string;
  heat?: number;
  independentSources: number;
  itemCount: number;
  locked: boolean;
  contentType?: string;
  primarySourceName?: string;
  primarySourceTier?: string;
}

export interface StoryEntry {
  id: string;
  title: string;
  summary?: string;
  canonicalUrl: string;
  publishedAt?: string;
  observedAt?: string;
  contentType?: string;
  relationType: string;
  similarity?: number;
  sourceName: string;
  sourceTier: string;
  organization?: string;
}

export interface StoryDetail {
  story: StorySummary;
  timeline: StoryEntry[];
}

export function fetchStories(limit = 30, minSources = 1): Promise<StorySummary[]> {
  return getJson<StorySummary[]>(
    `/api/v1/stories?limit=${limit}&minSources=${minSources}`,
    [],
  );
}

export function fetchStory(slug: string): Promise<StoryDetail | null> {
  return getJson<StoryDetail | null>(
    `/api/v1/stories/${encodeURIComponent(slug)}`,
    null,
  );
}

export interface CategoryTab {
  key: string;
  label: string;
  total: number;
}

export function fetchCategories(): Promise<CategoryTab[]> {
  return getJson<CategoryTab[]>("/api/v1/categories", []);
}

export interface TopicNode {
  slug: string;
  name: string;
  description?: string | null;
  group: boolean;
  groupSlug: string;
  groupName: string;
  groupDescription?: string | null;
  total: number;
}

export interface TopicGroup {
  slug: string;
  name: string;
  description?: string | null;
  total: number;
  children: TopicNode[];
}

export async function fetchTopicMap(): Promise<TopicGroup[]> {
  const nodes = await getJson<TopicNode[]>("/api/v1/topics/map", []);
  const groups = new Map<string, TopicGroup>();

  for (const node of nodes) {
    let group = groups.get(node.groupSlug);
    if (!group) {
      group = {
        slug: node.groupSlug,
        name: node.groupName,
        description: node.groupDescription,
        total: 0,
        children: [],
      };
      groups.set(node.groupSlug, group);
    }
    // The group's own row carries the heading, not a child chip: items tagged
    // with the parent slug directly still count toward the group total.
    if (node.group) {
      group.total += node.total;
    } else {
      group.children.push(node);
      group.total += node.total;
    }
  }

  return [...groups.values()];
}

export interface SourceHealth {
  id: string;
  name: string;
  organization: string;
  profile: string;
  priority: string;
  tier: string;
  runtimeState: string;
  contentAccess: string;
  lastSuccessAt?: string | null;
  lastErrorCode?: string | null;
  consecutiveFailures: number;
  nextPollAt?: string | null;
  /** Operator override of the registry: null means "follow config/sources.yaml". */
  operatorEnabled?: boolean | null;
  operatorNote?: string | null;
  items: number;
  fulltextSuccessRate?: number | null;
}

export function fetchSourceHealth(): Promise<SourceHealth[]> {
  return getJson<SourceHealth[]>("/api/v1/admin/sources", []);
}

/**
 * One card on a topic-map dimension that is not the topic vocabulary.
 *
 * Vendors and content forms share a shape because they are the same thing to a
 * reader: a name, a blurb, and how many items are behind it. They differ only
 * in where the count comes from — `item_entity` for one, `content_type` for the
 * other — and that difference belongs in SQL, not in two near-identical types.
 */
export interface MapCard {
  slug: string;
  name: string;
  description?: string | null;
  total: number;
}

export function fetchVendorMap(): Promise<MapCard[]> {
  return getJson<MapCard[]>("/api/v1/vendors/map", []);
}

export function fetchContentTypeMap(): Promise<MapCard[]> {
  return getJson<MapCard[]>("/api/v1/content-types/map", []);
}

export function fetchVendorItems(slug: string, limit = 40): Promise<ContentItem[]> {
  return getJson<ContentItem[]>(
    `/api/v1/vendors/${encodeURIComponent(slug)}?limit=${limit}`,
    [],
  );
}

export interface ReportSummary {
  date: string;
  title: string;
  summary: string;
  itemCount: number;
  generatedAt: string;
  modelName?: string | null;
}

export interface ReportDetail extends ReportSummary {
  bodyMarkdown: string;
  promptVersion?: string | null;
}

export type ReportPeriod = "daily" | "weekly" | "monthly";

export const REPORT_PERIODS: { key: ReportPeriod; label: string; blurb: string }[] = [
  { key: "daily", label: "日报", blurb: "当天精选的逐条速览" },
  { key: "weekly", label: "周报", blurb: "一周之内反复出现的方向与变化" },
  { key: "monthly", label: "月报", blurb: "一个月的格局判断与主线回顾" },
];

export function normalisePeriod(value?: string): ReportPeriod {
  return value === "weekly" || value === "monthly" ? value : "daily";
}

export function fetchReports(limit = 30, period: ReportPeriod = "daily"): Promise<ReportSummary[]> {
  return getJson<ReportSummary[]>(`/api/v1/reports?period=${period}&limit=${limit}`, []);
}

export function fetchReport(
  period: ReportPeriod,
  key: string,
): Promise<ReportDetail | null> {
  return getJson<ReportDetail | null>(
    `/api/v1/reports/${period}/${encodeURIComponent(key)}`,
    null,
  );
}

/**
 * Label a period key for display.
 *
 * Weekly keys are ISO weeks (2026-W31), which readers cannot date at a glance,
 * so the label spells out the month range instead of echoing the key.
 */
export function formatPeriodKey(period: ReportPeriod, key: string): string {
  if (period === "monthly") {
    const [year, month] = key.split("-");
    return `${year} 年 ${Number(month)} 月`;
  }
  if (period === "weekly") {
    const match = /^(\d{4})-W(\d{2})$/.exec(key);
    if (!match) return key;
    const [, year, week] = match;
    return `${year} 年第 ${Number(week)} 周`;
  }
  const [year, month, day] = key.split("-");
  return `${year} 年 ${Number(month)} 月 ${Number(day)} 日`;
}

/**
 * Bucket an archive into headed sections.
 *
 * The bucket depends on the period. Daily reports group by month; weekly reports
 * group by year, because an ISO week key carries no month and a week can span
 * two of them; monthly reports group by year as well, since a month-per-section
 * archive would be one entry per heading.
 */
export function groupReports(
  period: ReportPeriod,
  reports: ReportSummary[],
): Map<string, ReportSummary[]> {
  const groups = new Map<string, ReportSummary[]>();

  for (const report of reports) {
    const [year, month] = report.date.split("-");
    const label =
      period === "daily" && month ? `${year} 年 ${Number(month)} 月` : `${year} 年`;

    const bucket = groups.get(label);
    if (bucket) bucket.push(report);
    else groups.set(label, [report]);
  }
  return groups;
}

export function fetchTopics(): Promise<TopicSummary[]> {
  return getJson<TopicSummary[]>("/api/v1/topics", []);
}

export function fetchTopicItems(slug: string, limit = 30): Promise<ContentItem[]> {
  return getJson<ContentItem[]>(
    `/api/v1/topics/${encodeURIComponent(slug)}?limit=${limit}`,
    [],
  );
}

export function fetchItemTopics(id: string): Promise<TopicRef[]> {
  return getJson<TopicRef[]>(`/api/v1/items/${id}/topics`, []);
}

/**
 * Group items by calendar day for the date-sectioned feed (AHR-FEAT-101).
 *
 * Bucketed by the display timezone, not UTC: slicing the ISO string put
 * anything published after 08:00 Beijing time under the previous day's heading.
 */
/**
 * Append a freshly fetched page onto the accumulated feed.
 *
 * De-duplication is not defensive tidiness. Ingestion runs hourly, so the feed
 * shifts under a reader who is paging through it: an item that was on page one
 * when they loaded it can reappear on page two after newer items push it down.
 * Concatenating blindly renders two cards with the same React key.
 */
export function appendItems(
  current: ContentItem[],
  incoming: ContentItem[],
): ContentItem[] {
  const seen = new Set(current.map((item) => item.id));
  return [...current, ...incoming.filter((item) => !seen.has(item.id))];
}

export function groupByDay(items: ContentItem[]): Map<string, ContentItem[]> {
  const groups = new Map<string, ContentItem[]>();
  for (const item of items) {
    const stamp = item.publishedAt ?? item.observedAt;
    const day = dayKey(stamp) ?? "未知日期";
    const bucket = groups.get(day);
    if (bucket) {
      bucket.push(item);
    } else {
      groups.set(day, [item]);
    }
  }
  return groups;
}

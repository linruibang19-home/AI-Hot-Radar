/**
 * Server-side client for core-api.
 *
 * The browser never talks to core-api directly (AHR-ARCH-200 §3: the web tier
 * must not reach past the API), so these run during SSR only.
 */

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

async function getJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      // Content updates continuously; a short revalidation window keeps the
      // feed fresh without hammering the API on every request.
      next: { revalidate: 60 },
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
} = {}): Promise<ItemPage> {
  const query = new URLSearchParams();
  if (params.limit) query.set("limit", String(params.limit));
  if (params.cursor) query.set("cursor", params.cursor);
  if (params.q) query.set("q", params.q);
  if (params.contentType) query.set("contentType", params.contentType);

  const suffix = query.toString() ? `?${query}` : "";
  return getJson<ItemPage>(`/api/v1/items${suffix}`, EMPTY_PAGE);
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

export function fetchSelected(days = 7, limit = 40): Promise<SelectedItem[]> {
  return getJson<SelectedItem[]>(`/api/v1/selected?days=${days}&limit=${limit}`, []);
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
  items: number;
  fulltextSuccessRate?: number | null;
}

export function fetchSourceHealth(): Promise<SourceHealth[]> {
  return getJson<SourceHealth[]>("/api/v1/admin/sources", []);
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

export function fetchReports(limit = 30): Promise<ReportSummary[]> {
  return getJson<ReportSummary[]>(`/api/v1/reports?limit=${limit}`, []);
}

export function fetchDailyReport(date: string): Promise<ReportDetail | null> {
  return getJson<ReportDetail | null>(`/api/v1/reports/daily/${date}`, null);
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

/** Group items by calendar day for the date-sectioned feed (AHR-FEAT-101). */
export function groupByDay(items: ContentItem[]): Map<string, ContentItem[]> {
  const groups = new Map<string, ContentItem[]>();
  for (const item of items) {
    const stamp = item.publishedAt ?? item.observedAt;
    const day = stamp ? stamp.slice(0, 10) : "未知日期";
    const bucket = groups.get(day);
    if (bucket) {
      bucket.push(item);
    } else {
      groups.set(day, [item]);
    }
  }
  return groups;
}

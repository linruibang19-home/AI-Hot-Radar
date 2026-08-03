import type { MetadataRoute } from "next";

import { REPORT_PERIODS, fetchReports, fetchTopics } from "@/lib/api";

const SITE_URL = process.env.PUBLIC_BASE_URL ?? "http://localhost:3000";

// Rendered per request rather than at build time. The API client is
// deliberately uncached, which Next cannot reconcile with prerendering — it
// logged a dynamic-server error and fell back to an empty list, publishing a
// sitemap with no topics or reports in it.
export const dynamic = "force-dynamic";

/**
 * Sitemap covering the public routes.
 *
 * Individual items are deliberately excluded: the canonical URL for a piece of
 * content is the publisher's, not ours (AHR-SOURCE-900 §2), so listing hundreds
 * of excerpt pages would compete with the sources we link to.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: SITE_URL, changeFrequency: "hourly", priority: 1 },
    { url: `${SITE_URL}/items`, changeFrequency: "hourly", priority: 0.8 },
    { url: `${SITE_URL}/reports`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/topics`, changeFrequency: "daily", priority: 0.6 },
  ];

  const [topics, ...periods] = await Promise.all([
    fetchTopics(),
    ...REPORT_PERIODS.map((entry) => fetchReports(60, entry.key)),
  ]);

  const reportRoutes = REPORT_PERIODS.flatMap((entry, index) =>
    periods[index].map((report) => ({
      url: `${SITE_URL}/reports/${entry.key}/${report.date}`,
      lastModified: report.generatedAt,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  );

  return [
    ...staticRoutes,
    ...topics.map((topic) => ({
      url: `${SITE_URL}/topics/${topic.slug}`,
      changeFrequency: "daily" as const,
      priority: 0.5,
    })),
    ...reportRoutes,
  ];
}

import type { MetadataRoute } from "next";

import { fetchReports, fetchTopics } from "@/lib/api";

const SITE_URL = process.env.PUBLIC_BASE_URL ?? "http://localhost:3000";

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

  const [topics, reports] = await Promise.all([fetchTopics(), fetchReports(30)]);

  return [
    ...staticRoutes,
    ...topics.map((topic) => ({
      url: `${SITE_URL}/topics/${topic.slug}`,
      changeFrequency: "daily" as const,
      priority: 0.5,
    })),
    ...reports.map((report) => ({
      url: `${SITE_URL}/reports/daily/${report.date}`,
      lastModified: report.generatedAt,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}

import type { MetadataRoute } from "next";

const SITE_URL = process.env.PUBLIC_BASE_URL ?? "http://localhost:3000";

/**
 * Crawl policy.
 *
 * The admin view is disallowed: it exposes source diagnostics and error codes
 * that are operational detail, not public content. It is unauthenticated today
 * (auth is M5), so keeping it out of indexes is the minimum protection.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/admin/"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}

import type { MetadataRoute } from "next";

const SITE_URL = process.env.PUBLIC_BASE_URL ?? "http://localhost:3000";

// Rendered per request, exactly like `sitemap.ts` and for the same reason.
//
// As a static route Next resolved `PUBLIC_BASE_URL` at `docker build` time —
// inside a GitHub Actions container, where it is not set — and baked the
// fallback into the image. Production therefore published
// `Sitemap: http://localhost:3000/sitemap.xml`, pointing every crawler at its
// own machine, so the sitemap that lists every topic and report was never
// fetched. The site was left to be discovered link by link.
//
// The bug hid because the neighbouring `sitemap.ts` was correct: it already
// declared this, so the two files read the same variable and only one of them
// was wrong.
export const dynamic = "force-dynamic";

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

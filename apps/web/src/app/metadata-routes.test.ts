import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Both files read `PUBLIC_BASE_URL`, which only exists at runtime.
 *
 * A metadata route without `force-dynamic` is resolved during `next build` — in
 * CI, where that variable is unset — and the fallback is baked into the image.
 * That is not a build error and not a runtime error: the route keeps answering
 * 200 with `http://localhost:3000` in it. `robots.txt` shipped that way to
 * production and pointed every crawler at its own machine.
 *
 * Asserted on the source rather than by rendering, because the defect is the
 * absence of a declaration, and a rendered route in a test process would happily
 * pick up whatever environment the test runner has.
 */
const routes = ["robots.ts", "sitemap.ts"] as const;

describe("public metadata routes", () => {
  it.each(routes)("%s is rendered per request, not baked at build time", (file) => {
    const source = readFileSync(fileURLToPath(new URL(`./${file}`, import.meta.url)), "utf8");

    expect(source).toContain("PUBLIC_BASE_URL");
    expect(source).toMatch(/export const dynamic = "force-dynamic"/);
  });
});

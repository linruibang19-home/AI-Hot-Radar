import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

/**
 * Click through the whole site in a real browser.
 *
 * Server-side checks (curl every route, assert 200) already pass and would not
 * have caught any of the three defects the feed shipped with — all of them were
 * browser behaviour. This walks the site the way a reader does and fails on
 * anything the console reports, which is the class of problem a 200 hides:
 * hydration mismatches, failed client fetches, React key collisions.
 */

/** Console noise that is not a defect in this app. */
const IGNORED = [
  // React DevTools nag, emitted on every dev-mode page load.
  /Download the React DevTools/i,
  // Chromium emits this for the favicon on some pages.
  /favicon\.ico/i,
];

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message: ConsoleMessage) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (IGNORED.some((pattern) => pattern.test(text))) return;
    errors.push(text);
  });
  page.on("pageerror", (error) => errors.push(String(error)));
  return errors;
}

const PAGES: Array<{ path: string; name: string; expect: string }> = [
  { path: "/", name: "精选首页", expect: "main" },
  { path: "/items", name: "全部动态", expect: "details.tl-day" },
  { path: "/hot", name: "热点榜", expect: "main" },
  { path: "/stories", name: "事件追踪", expect: "main" },
  { path: "/topics", name: "主题地图", expect: "main" },
  { path: "/reports", name: "AI 日报", expect: "main" },
  { path: "/ask", name: "RAG 问答", expect: ".ask-input" },
  { path: "/admin/sources", name: "信源后台", expect: "main" },
];

test.describe("navigation", () => {
  for (const target of PAGES) {
    test(`${target.name} renders without console errors`, async ({ page }) => {
      const errors = collectErrors(page);

      const response = await page.goto(target.path);
      expect(response?.status(), `${target.path} status`).toBe(200);
      await expect(page.locator(target.expect).first()).toBeVisible();

      // A page that renders but logs a failed fetch is broken in a way the
      // status code cannot express.
      expect(errors, `console errors on ${target.path}`).toEqual([]);
    });
  }

  test("the sidebar reaches every section", async ({ page }) => {
    await page.goto("/");
    const links = page.locator("nav a[href^='/']");
    expect(await links.count()).toBeGreaterThan(5);

    // Every nav target must resolve. A 404 behind a nav link is worse than a
    // missing link: it looks like the feature exists.
    const hrefs = await links.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("href")).filter(Boolean),
    );
    for (const href of new Set(hrefs)) {
      const response = await page.request.get(href as string);
      expect(response.status(), `${href} from sidebar`).toBeLessThan(400);
    }
  });

  test("a slow dynamic route acknowledges the click immediately", async ({
    page,
  }) => {
    await page.goto("/");

    // Dynamic App Router navigation is a fetch for an RSC payload. Hold that
    // payload briefly to make the in-between state deterministic instead of
    // depending on how fast the local Core API happens to respond.
    await page.route(/\/hot\?_rsc=/, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 600));
      await route.continue();
    });

    const target = page
      .locator(".sidebar")
      .getByRole("link", { name: "热点榜", exact: true });
    await target.click();

    await expect(target).toHaveAttribute("aria-busy", "true");
    // The already rendered article remains readable. Replacing it with a
    // full-screen skeleton made a 150–200ms request feel like a page reload.
    await expect(page.locator(".route-loading")).toHaveCount(0);
    await expect(page.locator("main")).toContainText("精选");
    await expect(page).toHaveURL(/\/hot$/);
    await expect(target).not.toHaveAttribute("aria-busy", "true");
  });

  test("a selected item opens its detail page and links to the source", async ({
    page,
  }) => {
    await page.goto("/");
    const first = page.locator('a[href^="/items/"]').first();
    await first.click();

    await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}/);
    // Every item must offer the original: the site's claim is that AI-written
    // summaries are checkable, and that requires the link.
    await expect(
      page.locator('a[target="_blank"][href^="http"]').first(),
    ).toBeVisible();
  });

  test("a story opens its timeline", async ({ page }) => {
    await page.goto("/stories");
    await expect(page.getByText("参与来源").first()).toBeVisible();
    const first = page.locator('a[href^="/stories/"]').first();
    await first.click();

    await expect(page).toHaveURL(/\/stories\/.+/);
    await expect(page.getByRole("heading", { name: "来源时间线" })).toBeVisible();
    await expect(page.getByText(/相似度 \d/)).toHaveCount(0);
  });

  test("a topic opens its filtered list", async ({ page }) => {
    await page.goto("/topics");
    await page.locator('a[href^="/topics/"]').first().click();

    await expect(page).toHaveURL(/\/topics\/.+/);
    await expect(page.locator('a[href^="/items/"]').first()).toBeVisible();
  });

  test("a report opens with its entries linked to the publisher", async ({
    page,
  }) => {
    await page.goto("/reports");
    await page.locator('a[href^="/reports/"]').first().click();

    await expect(page).toHaveURL(/\/reports\/\w+\/.+/);

    // Entries link out to the publisher, deliberately not to a local copy —
    // ADR-009. Asserting an internal /items/ link here would be asserting the
    // opposite of the locked decision. §7 traceability is satisfied by the
    // outbound link plus the source name shown beside it.
    const outbound = page.locator('.report-page a[target="_blank"][href^="http"]');
    expect(await outbound.count()).toBeGreaterThan(0);
  });

  test("the back control returns to the list", async ({ page }) => {
    await page.goto("/items");
    await page.locator('a[href^="/items/"]').first().click();
    await expect(page).toHaveURL(/\/items\/[0-9a-f-]{36}/);

    await page.locator(".back-link, a[href='/items']").first().click();
    await expect(page).toHaveURL(/\/items\/?$/);
  });

  test("the site is usable at mobile width", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/");

    await expect(page.locator("main")).toBeVisible();
    // Horizontal overflow is the classic small-screen defect and is invisible
    // at desktop width.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(overflow, "page scrolls horizontally at 375px").toBe(false);
  });
});

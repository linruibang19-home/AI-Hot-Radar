import { expect, test } from "@playwright/test";

/**
 * Regression cover for the 全部 AI 动态 feed.
 *
 * Every test corresponds to a defect that actually shipped, and none of them
 * could have been caught by a unit test or by inspecting the server HTML.
 *
 * The feed no longer paginates. It used to page by item count while being read
 * by date, and on this corpus one day holds close to 200 items — so reaching
 * the previous date took eight clicks that each looked like nothing had
 * happened. Every date now renders from a GROUP BY, and a day's items load the
 * first time it is opened.
 */

const DAY = "details.tl-day";
const ROW = ".tl-row";

/**
 * Wait until a day stops growing, and return the count.
 *
 * Exact equality with the header cannot be asserted: the header comes from a
 * Redis-cached GROUP BY (2 min TTL) while the rows are fetched live, and
 * ingestion keeps writing while the suite runs. Two identical consecutive reads
 * mean the client finished loading, which is the property these tests are
 * actually about.
 */
async function settledRowCount(
  day: import("@playwright/test").Locator,
): Promise<number> {
  let previous = -1;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const current = await day.locator(ROW).count();
    if (current > 0 && current === previous) return current;
    previous = current;
    await day.page().waitForTimeout(500);
  }
  return previous;
}

test.describe("items feed", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/items");
    await expect(page.locator(DAY).first()).toBeVisible();
  });

  test("every publication date is listed, not just a first page", async ({ page }) => {
    // The corpus spans months. A page showing only a handful of days means the
    // count-based pagination has crept back in.
    expect(await page.locator(DAY).count()).toBeGreaterThan(20);
  });

  test("the newest three days are expanded, the rest collapsed", async ({ page }) => {
    const days = page.locator(DAY);
    const total = await days.count();
    for (let index = 0; index < Math.min(3, total); index += 1) {
      await expect(days.nth(index)).toHaveAttribute("open", "");
    }
    if (total > 3) {
      await expect(days.nth(3)).not.toHaveAttribute("open", "");
    }
  });

  test("an expanded day holds roughly what its header claims", async ({ page }) => {
    // The header count comes from a GROUP BY and the rows from a paged query.
    // A large gap means one of them filters differently — which is exactly what
    // happened when the server-rendered first page (50) was marked complete and
    // the client never fetched the remaining 39.
    const first = page.locator(DAY).first();
    const label = await first.locator(".tl-weekday").textContent();
    const claimed = Number(label?.match(/(\d+)\s*条/)?.[1] ?? 0);

    const loaded = await settledRowCount(first);
    expect(loaded).toBeGreaterThan(0);
    expect(Math.abs(loaded - claimed)).toBeLessThanOrEqual(5);
  });

  test("a collapsed day loads its items when opened", async ({ page }) => {
    const days = page.locator(DAY);
    const fourth = days.nth(3);
    expect(await fourth.locator(ROW).count()).toBe(0);

    await fourth.locator("summary").click();

    await expect(fourth).toHaveAttribute("open", "");
    expect(await settledRowCount(fourth)).toBeGreaterThan(0);
  });

  test("reopening a day does not duplicate its items", async ({ page }) => {
    const first = page.locator(DAY).first();

    // Settle first. The server renders one page and the client fetches the
    // remainder, so sampling immediately catches the partial list and the
    // later completion looks like duplication.
    const before = await settledRowCount(first);
    expect(before).toBeGreaterThan(0);

    await first.locator("summary").click();
    await first.locator("summary").click();
    await expect(first).toHaveAttribute("open", "");

    // Asserted by identity, not by count. A second fetch appending onto the
    // same day is what this test is for, and duplicate hrefs detect it exactly.
    // An equality check on the count also *fails* when the pipeline writes a
    // new item mid-test, which it does every 15 minutes — that made this test
    // fail roughly one run in four for a reason that was never the defect.
    await expect
      .poll(async () => {
        const hrefs = await first
          .locator('a[href^="/items/"]')
          .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
        return hrefs.length - new Set(hrefs).size;
      })
      .toBe(0);

    // The list must also not have shrunk: a re-render that dropped rows would
    // pass a duplicate check while still being broken.
    expect(await first.locator(ROW).count()).toBeGreaterThanOrEqual(before);
  });

  test("no duplicate item appears anywhere in the feed", async ({ page }) => {
    // Ingestion runs hourly, so the feed shifts under a reader and the same
    // item can return under a later cursor within one day's fetch loop.
    await settledRowCount(page.locator(DAY).first());
    const hrefs = await page.locator('a[href^="/items/"]').evaluateAll((links) =>
      links.map((link) => link.getAttribute("href")),
    );
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  test("a category filter re-derives the dates", async ({ page }) => {
    const before = await page.locator(DAY).count();

    // Navigating rather than clicking the tab: the assertion is about the day
    // list being filtered alongside the items, and coupling it to the tab's
    // accessible name makes it fail for reasons that have nothing to do with
    // that. The tab's own markup is covered by the unit tests.
    await page.goto("/items?category=model");
    await expect(page.locator(DAY).first()).toBeVisible();

    expect(await page.locator(DAY).count()).toBeLessThan(before);
  });
});

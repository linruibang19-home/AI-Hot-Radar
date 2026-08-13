import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a running stack.
 *
 * These exist because the feed's defects were all invisible to unit tests and
 * to server-rendered HTML: "load more" replaced the list instead of extending
 * it, a collapsed <details> swallowed appended items, and paginating by item
 * count meant a day with 192 items took eight clicks to get past. Every one of
 * those is a browser behaviour, and every one shipped.
 *
 * No `webServer` block: the stack runs under Compose, and starting a second
 * Next.js instance here would talk to a core-api that is not on its network.
 * Point BASE_URL at the running site instead.
 *
 * Playwright is deliberately *not* a dependency of the web app. Adding it there
 * put it into the runtime image's `npm ci` and broke the build for a tool the
 * server never runs. The official image already carries the package and the
 * browsers, so the suite needs no install step at all:
 *
 *   docker run --rm --network host -v "$PWD/apps/web/e2e:/e2e" -w /e2e \
 *     mcr.microsoft.com/playwright:v1.49.1-noble npx playwright test
 */
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});

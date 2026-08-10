import { expect, test } from "@playwright/test";

/**
 * The question box and its SSE progress stream.
 *
 * These need a real browser for the same reason the feed tests do: the thing
 * under test is streaming behaviour in the client. `ReadableStream` reads,
 * partial SSE frames spanning two chunks, and incremental re-render are all
 * invisible to a unit test and to server HTML.
 *
 * The query costs three provider round trips (embed, rerank, generate) and was
 * measured at p50 10.5s, with a 43s tail observed in practice — hence the long
 * timeouts. They are generous on purpose: a flaky failure here would be blamed
 * on the stream when it was the model being slow.
 */

const STEP = ".ask-step";

/** Sources collapse by default now; open them before asserting on the cards. */
async function openSources(page: import("@playwright/test").Page) {
  const sources = page.locator(".ask-sources");
  if (await sources.count()) await sources.locator("summary").click();
}

/**
 * Each test asks as a different reader.
 *
 * `/ask` is metered at 3 per minute per caller. This file fires eleven queries
 * of roughly thirteen seconds each, so from a single address the fourth one in
 * any minute is refused — and the refusal arrives as a missing answer, which
 * reads exactly like a broken assertion. Two runs failed on three different
 * tests each before the cause was clear.
 *
 * TEST-NET-2 (198.51.100.0/24) is the documentation range, so these can never
 * collide with a real visitor's bucket.
 */
let reader = 0;

/**
 * Force the uncached pipeline for the tests that are about the pipeline.
 *
 * Answers are cached (ADR-0017) and a cache hit runs no pipeline at all, so the
 * streaming assertions were quietly testing the cached path and finding no
 * stage events at all.
 *
 * A unique-question nonce was tried first and did not work — which is itself a
 * result worth keeping: appending `（#1754…）` to a long question leaves the two
 * embeddings above the 0.97 near-match threshold, so the semantic layer served
 * the cached answer anyway. Text cannot reliably force a miss; the explicit
 * directive can, and it is the same one an operator uses to re-run a suspect
 * answer.
 */
const UNCACHED = { "cache-control": "no-cache" };

test.describe("ask", () => {
  test.beforeEach(async ({ page }) => {
    reader += 1;
    await page.setExtraHTTPHeaders({ "x-forwarded-for": `198.51.100.${reader}` });
    await page.goto("/ask");
  });

  test("progress appears long before the answer does", async ({ page }) => {
    // The whole point of the stream. Generation alone is 5.7s at p50, so if
    // the first paint waited for the answer this would time out.
    await page.setExtraHTTPHeaders({ ...UNCACHED, "x-forwarded-for": `198.51.100.${reader}` });
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();

    await expect(page.locator(STEP).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(".ask-step.is-done").first()).toBeVisible({
      timeout: 30_000,
    });
  });

  test("stages complete in pipeline order", async ({ page }) => {
    await page.setExtraHTTPHeaders({ ...UNCACHED, "x-forwarded-for": `198.51.100.${reader}` });
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();

    // "理解问题" resolves in under a millisecond; "生成回答" is last by
    // several seconds. If frames were buffered and flushed together, both
    // would land in the same paint and this ordering would not hold.
    await expect(page.locator(STEP).first()).toHaveClass(/is-done/, {
      timeout: 20_000,
    });
    await expect(page.locator(STEP).last()).not.toHaveClass(/is-done/);
  });

  test("an answer arrives with its sources, or is a stated refusal", async ({
    page,
  }) => {
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();

    await expect(page.locator(".ask-body, .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });

    // A refusal is a valid outcome and must not be treated as failure — the
    // locked constraint is that model output is not a trusted fact. What is
    // *not* allowed is an answer with no sources.
    await openSources(page);
    const refused = await page.locator(".ask-refusal").count();
    if (!refused) {
      await expect(page.locator(".ask-source").first()).toBeVisible();
    }
  });

  test("every citation links to a real source and is numbered", async ({
    page,
  }) => {
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();
    await expect(page.locator(".ask-body, .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });

    await openSources(page);
    const sources = page.locator(".ask-source");
    const count = await sources.count();
    for (let index = 0; index < count; index += 1) {
      // Asserted on the outbound link specifically. The card's *first* anchor
      // is now the internal detail page, so `.first()` would silently start
      // testing something else — which is what it did when the card gained a
      // second entry point.
      const outbound = sources.nth(index).locator('a[target="_blank"][href^="http"]');
      // A citation the server could not resolve has no business rendering:
      // AHR-API-500 §4 has the server resolve them precisely so a reference
      // the model invented cannot reach the page.
      expect(await outbound.count()).toBeGreaterThan(0);
      await expect(sources.nth(index).locator(".ask-source-no")).toContainText("[");
    }
  });

  test("a citation marker in the answer reaches its source", async ({ page }) => {
    // The claim this product makes is that every fact carries a checkable
    // source. Until these markers became controls, the reader had to match
    // `[1]` against a list by eye — the guarantee existed on the server and
    // nowhere the reader could reach.
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();
    await expect(page.locator(".ask-body, .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });
    test.skip(
      (await page.locator(".ask-refusal").count()) > 0,
      "refusal has no citations to reach",
    );

    await openSources(page);
    const marker = page.locator(".cite-ref").first();
    await expect(marker).toBeVisible();
    await marker.click();

    // The corresponding source must exist and become the highlighted one.
    // Scoped to the turn: anchors are `cite-<queryId>-<n>` now that several
    // answers share the page, because `#cite-3` in a three-turn conversation
    // would have sent the reader to the oldest of three sources numbered 3.
    const number = (await marker.textContent())?.trim();
    await expect(
      page.locator(".chat-turn").last().locator(`[id$="-${number}"].ask-source`),
    ).toHaveClass(/is-active/);
  });

  test("the resolved retrieval plan is shown", async ({ page }) => {
    // "最近" is resolved to an absolute interval before retrieval. Showing it
    // lets a reader see the window caught the wrong week, instead of
    // concluding the system is wrong.
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();
    await expect(page.locator(".ask-body, .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });

    await expect(page.locator(".ask-plan-chip").first()).toBeVisible();
    await expect(page.locator(".ask-plan-range")).toBeVisible();
  });

  test("each source carries the tier the ranker used", async ({ page }) => {
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();
    await expect(page.locator(".ask-body, .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });
    test.skip((await page.locator(".ask-refusal").count()) > 0, "refusal has no sources");

    // §6 boosts by source tier; the reader deciding whether to believe a claim
    // deserves the same signal the ranker had.
    await openSources(page);
    const badges = page.locator(".ask-source .tier-badge");
    expect(await badges.count()).toBeGreaterThan(0);
  });

  test("a source links inward as well as outward", async ({ page }) => {
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();
    await expect(page.locator(".ask-body, .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });
    test.skip((await page.locator(".ask-refusal").count()) > 0, "refusal has no sources");

    await openSources(page);
    const source = page.locator(".ask-source").first();
    // Inward to the site's own analysis, outward to the publisher. ADR-009
    // keeps the publisher link; it is not replaced, only preceded.
    await expect(source.locator('a[href^="/items/"]')).toBeVisible();
    await expect(source.locator('a[target="_blank"][href^="http"]')).toBeVisible();
  });

  test("the retrieval trace survives the answer, collapsed", async ({ page }) => {
    // This asserted the opposite until now — the trace was removed once the
    // answer arrived. That threw away the one artefact showing *how* the answer
    // was reached, which is the thing distinguishing this from a chat box. It
    // collapses so the answer is read first, but it stays.
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();
    await expect(page.locator(".ask-body, .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });

    const trace = page.locator(".ask-trace");
    await expect(trace).toBeVisible();
    await expect(trace).not.toHaveAttribute("open", "");

    await trace.locator("summary").click();
    await expect(page.locator(STEP)).toHaveCount(4);
  });

  test("the previous answer survives asking a follow-up", async ({ page }) => {
    // The defect this exists for, reported four times. Submitting a follow-up
    // ran `setAnswer(null)` to show progress, so the previous exchange vanished
    // the instant the next question was sent — a working multi-turn backend
    // rendering as "ask, wipe, ask again".
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();
    await expect(page.locator(".chat-turn .ask-body, .chat-turn .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });

    const first = await page.locator(".chat-turn").first().locator(".chat-bubble").textContent();

    await page.locator(".ask-input").fill("它修复了什么问题？");
    await page.locator(".ask-submit").click();

    // Asserted *while the second turn is still running*, which is exactly the
    // moment the page used to go blank.
    await expect(page.locator(".chat-turn.is-pending")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".chat-turn").first().locator(".chat-bubble")).toHaveText(
      first ?? "",
    );
    await expect(page.locator(".chat-turn").first().locator(".ask-answer")).toBeVisible();

    // And once it lands, both are on screen.
    await expect(page.locator(".chat-turn")).toHaveCount(2, { timeout: 120_000 });
  });

  test("a conversation survives a reload", async ({ page }) => {
    // It is written to `rag_query` in the same transaction as the answer, and
    // the thread id is kept for the sitting, so a reload must find it — the
    // page used to drop the conversation and show strangers' questions instead.
    await page.locator(".ask-input").fill("llama.cpp 最近发布了哪些版本？");
    await page.locator(".ask-submit").click();
    await expect(page.locator(".chat-turn .ask-body, .chat-turn .ask-refusal")).toBeVisible({
      timeout: 120_000,
    });

    await page.reload();
    await expect(page.locator(".chat-turn")).toHaveCount(1, { timeout: 20_000 });
    await expect(page.locator(".chat-turn .ask-body, .chat-turn .ask-refusal")).toBeVisible();
  });

  test("history lists conversations, and reopening one continues it", async ({ page }) => {
    // The resumable unit is the thread. A flat list of turns showed the same
    // 「那它呢」 three times with nothing saying what each was following up on,
    // and offered nothing to reopen.
    await page.locator(".ask-history summary").click();
    const rows = page.locator(".ask-history-row");
    await expect(rows.first()).toBeVisible({ timeout: 20_000 });

    await rows.first().locator(".ask-history-head").click();
    await expect(page.locator(".chat-turn").first()).toBeVisible({ timeout: 20_000 });
    // Reopened into the box, not into an expander below it.
    await expect(page.locator(".ask-history-body")).toHaveCount(0);
    // And the composer says the next question will continue this thread.
    await expect(page.locator(".chat-status")).toContainText("同一段对话");
  });
});

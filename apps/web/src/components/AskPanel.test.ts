import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * The structural property behind "the conversation stayed on screen".
 *
 * This defect was reported four times and fixed twice, because both fixes
 * treated the symptom. The page held one `answer`, submitting a follow-up ran
 * `setAnswer(null)` to show progress, and the previous exchange was gone the
 * instant the next question was sent — so a working multi-turn backend rendered
 * as "ask, wipe, ask again". Patching the clear left the same shape in place
 * for the next edit to re-break.
 *
 * The rebuild removed the slot. `turns` is append-only and is the only thing
 * deciding what is rendered; the question in flight is a separate value that
 * lives *after* the transcript rather than in place of it. These assertions are
 * on the source text rather than on a rendered tree — this app has no React
 * test renderer, and the property worth pinning is which state exists at all,
 * which is exactly what source-level assertions can see. The behaviour on top
 * of it belongs to the Playwright suite in `e2e/ask.spec.ts`.
 */

const SOURCE = readFileSync(
  fileURLToPath(new URL("./AskPanel.tsx", import.meta.url)),
  "utf8",
);

describe("the transcript is append-only", () => {
  it("has no single-answer slot for the next question to overwrite", () => {
    // The exact shape that caused it. `answer` held one payload and every code
    // path that wanted to show something else had to destroy it first.
    expect(SOURCE).not.toMatch(/setAnswer\(/);
    expect(SOURCE).not.toMatch(/const \[answer, /);
  });

  it("never empties the transcript except when the reader asks for a new topic", () => {
    const clears = [...SOURCE.matchAll(/setTurns\(\[\]\)/g)];
    expect(clears).toHaveLength(1);
    // And that one is inside 换个新话题, the control that says it will.
    const fresh = SOURCE.slice(
      SOURCE.indexOf("function startFresh"),
      SOURCE.indexOf("async function resume"),
    );
    expect(fresh).toContain("setTurns([])");
  });

  it("adds a landed answer rather than replacing what is there", () => {
    expect(SOURCE).toMatch(/setTurns\(\(prior\) => \[\.\.\.prior, landed\]\)/);
  });

  it("keeps the question in flight beside the transcript, not inside it", () => {
    // The second bug in the previous attempt: the running turn was spliced into
    // the thread list, so a conditional slice decided whether the newest answer
    // was visible. Getting that condition wrong made it vanish again.
    expect(SOURCE).toMatch(/const \[pending, setPending\]/);
    expect(SOURCE).not.toMatch(/thread\.slice\(/);
  });
});

describe("what the reader is shown about the conversation", () => {
  it("renders every turn through one renderer", () => {
    // Earlier turns used to be 140-character stubs on the reasoning that a past
    // answer's apparatus would bury the current one. Truncating the text threw
    // away what the reader came back for; a conversation you cannot re-read is
    // a log. One component now renders all of them.
    expect(SOURCE).toMatch(/function ChatTurn\(/);
    expect([...SOURCE.matchAll(/<ChatTurn/g)]).toHaveLength(1);
  });

  it("scopes citation anchors per turn", () => {
    // `#cite-3` was unique when one answer occupied the page. With several on
    // screen, clicking [3] in the newest answer would jump to the oldest.
    expect(SOURCE).toMatch(/cite-\$\{key\}-\$\{/);
  });

  it("resumes a thread rather than expanding one turn of it", () => {
    expect(SOURCE).toMatch(/async function resume\(/);
    expect(SOURCE).toMatch(/\/api\/ask\?threads=1/);
  });

  it("keeps the thread for one sitting, not indefinitely", () => {
    // A conversation resumed a week later would carry context the reader has
    // forgotten into a corpus that has moved on.
    expect(SOURCE).toMatch(/sessionStorage\.setItem\("ahr:conversation"/);
    // Usage, not the word: the comment above the call names `localStorage` in
    // order to say why it is not the one being used.
    expect(SOURCE).not.toMatch(/localStorage\./);
  });
});

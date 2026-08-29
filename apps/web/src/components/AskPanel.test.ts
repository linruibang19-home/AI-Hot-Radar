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

const TRACE = readFileSync(
  fileURLToPath(new URL("./AnswerTrace.tsx", import.meta.url)),
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

  it("closes the conversation list once it has handed a thread over", () => {
    // Left open, a stack of other conversations sits between the answer just
    // reopened and the box for asking the next question.
    const body = SOURCE.slice(SOURCE.indexOf("async function resume"));
    expect(body.slice(0, body.indexOf("} catch"))).toContain("setHistoryOpen(false)");
  });

  it("offers starting over as a control, in one fixed place", () => {
    // 换个新话题 used to be a chip inside the explanatory note under the
    // composer, and the reader looking for "new chat" found nothing.
    expect(SOURCE).toMatch(/className="chat-new"/);
    expect([...SOURCE.matchAll(/onClick=\{startFresh\}/g)]).toHaveLength(1);
    // Disabled when there is nothing to clear, never removed: a control that
    // disappears when idle is one that cannot be found when it is needed.
    expect(SOURCE).toMatch(/disabled=\{turns\.length === 0 && !pending\}/);
  });

  it("keeps the thread for one sitting, not indefinitely", () => {
    // A conversation resumed a week later would carry context the reader has
    // forgotten into a corpus that has moved on.
    expect(SOURCE).toMatch(/sessionStorage\.setItem\("ahr:conversation"/);
    // Usage, not the word: the comment above the call names `localStorage` in
    // order to say why it is not the one being used.
    expect(SOURCE).not.toMatch(/localStorage\./);
  });

  it("shows evidence quality without collapsing it into an opaque score", () => {
    // Support, independence and publisher count answer different questions, and
    // one blended percentage would look precise while hiding which part is
    // weak. They still travel together — now as the summary of the disclosure
    // they describe rather than as a block of their own above it.
    expect(SOURCE).toMatch(/function sourcesSummary\(/);
    expect(SOURCE).toContain("通过支持度校验");
    expect(SOURCE).toContain("家信源");
    expect(SOURCE).not.toContain("综合置信度");
  });

  it("sets concrete expectations before the first question", () => {
    // The three capability bullets became one sentence. What must survive is
    // that a first-time visitor is told the two things that make this not a
    // chat box before they type: answers are sourced, and it will refuse.
    expect(SOURCE).toContain("可回溯来源");
    expect(SOURCE).toContain("证据不足会拒答");
    expect(SOURCE).toContain('aria-label="示例问题"');
  });
});

/**
 * One funnel, stated once.
 *
 * A reader looking at one answer was shown the source count three times under
 * three names (5 家信源 / 4 家发布方 / 4 个信源, two of which meant the same
 * thing), the evidence count three times, and the candidate count twice — as
 * 101 in one panel and 40 in another, both correct and naming different
 * stages. Every one of those arrived with a feature that added its own
 * counter row and never looked at the ones already there.
 *
 * These guards are about *where* a number is allowed to appear, which is the
 * property that decayed. They are deliberately narrow: they name the strings
 * that were duplicated, not a general rule about counting.
 */
describe("pipeline numbers have exactly one home", () => {
  it("routes every retrieval count through the funnel, not the answer header", () => {
    // The chips these matched are the ones that restated a number stated again
    // further down the same answer.
    expect(SOURCE).not.toContain("段证据");
    expect(SOURCE).not.toContain("家信源</span>");
    expect(SOURCE).not.toContain("个信源");
    expect(SOURCE).not.toContain("同时检索");
  });

  it("renders one trace component per turn, not a progress panel beside it", () => {
    expect([...SOURCE.matchAll(/<AnswerTrace/g)]).toHaveLength(1);
    // The two panels that split the same chain in half.
    expect(SOURCE).not.toContain("检索过程");
    expect(SOURCE).not.toContain("为什么是这几条证据");
  });

  it("names each stage of the funnel rather than reusing one word for two", () => {
    // 「101 条候选」 and 「40 个候选」 were both labelled 候选. They are the
    // fusion output and the rerank window, and the funnel says so.
    expect(TRACE).toContain("召回 ");
    expect(TRACE).toContain("重排 ");
    expect(TRACE).toContain("证据 ");
    expect(TRACE).toContain("引用 ");
  });

  it("takes stage timings from the stored answer, not from the progress stream", () => {
    // A permalink never receives the SSE events, so a panel built from them
    // rendered with no timings at all on exactly the page meant to be shared.
    expect(TRACE).toContain("metrics.stages_ms");
    expect(TRACE).not.toMatch(/stages\.find\(/);
  });

  it("keeps the funnel summary outside the disclosure it opens", () => {
    // Collapsing the whole chain behind a click is the black box this feature
    // exists to remove; forty rows open by default is a different kind of
    // unreadable. The line states the funnel, the disclosure holds the evidence.
    const summary = TRACE.slice(TRACE.indexOf("<summary"), TRACE.indexOf("</summary>"));
    expect(summary).toContain("funnel-steps");
    expect(summary).toContain("召回");
  });

  it("defaults the candidate table to what reached the model", () => {
    // Forty rows on every turn is what the reader called redundant; the thirty
    // that were eliminated answer a question asked second.
    expect(TRACE).toMatch(/const inEvidence = rows\.filter\(/);
    expect(TRACE).toContain("展开全部");
  });
});

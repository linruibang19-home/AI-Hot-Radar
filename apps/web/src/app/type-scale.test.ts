import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * The stylesheet gets one type scale, and every rule uses it.
 *
 * `body` never declared a `font-size`, so each component sized itself against
 * the browser default and drifted independently: 199 declarations across 49
 * distinct values, 42 of them at or below 11px and the smallest at 9px. Chinese
 * stops being comfortable to read below about 12px, and the feed summary — the
 * most-read text on the site — had settled at 13.5px. Readers reported "too much
 * small text" three times; each round of hand-tuning individual rules fixed the
 * page in front of us and left the mechanism that produced it intact.
 *
 * Asserted on the source because that is where the drift happens. A rendered
 * page only shows the sizes that page uses, and the next stray `font-size: 11px`
 * will arrive on some page this suite does not open.
 */
const STYLESHEET = fileURLToPath(new URL("./globals.css", import.meta.url));
const SCALE = ["--fs-xs", "--fs-sm", "--fs-base", "--fs-md", "--fs-lg", "--fs-xl", "--fs-2xl", "--fs-3xl"];

/** `clamp()` and `em` are deliberate exceptions: fluid hero titles and one relative inset. */
const RELATIVE = /^(clamp\(|[\d.]+em$)/;

function declarations(): string[] {
  const css = readFileSync(STYLESHEET, "utf8");
  return [...css.matchAll(/font-size:\s*([^;]+);/g)].map((match) => match[1].trim());
}

describe("type scale", () => {
  it("defines the whole scale in one place", () => {
    const css = readFileSync(STYLESHEET, "utf8");
    for (const token of SCALE) {
      expect(css, `${token} is missing from :root`).toMatch(new RegExp(`${token}:\\s*\\d`));
    }
  });

  it("gives the document a baseline size", () => {
    // Without this every component sizes itself against the browser default and
    // the scale below is advisory rather than a system.
    const css = readFileSync(STYLESHEET, "utf8");
    expect(css).toMatch(/body\s*\{[^}]*font-size:\s*var\(--fs-/);
  });

  it("sizes every rule from the scale", () => {
    const strays = declarations().filter(
      (value) => !value.startsWith("var(--fs-") && !RELATIVE.test(value),
    );

    expect(strays, `use a --fs-* token instead of: ${strays.join(", ")}`).toEqual([]);
  });

  it("has no token below 12px", () => {
    // 9px, 10px and 11px were all in use. Badges and timestamps live at --fs-xs;
    // nothing needs to be smaller than that.
    const css = readFileSync(STYLESHEET, "utf8");
    const tokens = [...css.matchAll(/(--fs-[a-z0-9]+):\s*(\d+(?:\.\d+)?)px/g)];

    expect(tokens.length).toBe(SCALE.length);
    for (const [, name, px] of tokens) {
      expect(Number(px), `${name} is unreadable for CJK body text`).toBeGreaterThanOrEqual(12);
    }
  });
});

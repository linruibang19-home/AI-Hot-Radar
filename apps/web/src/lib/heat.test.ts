import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { heatBadge, heatStat, showsHeatBadge } from "./heat";

describe("showsHeatBadge", () => {
  it("hides the badge for a score that rounds to zero", () => {
    // The measured majority: 3029 of 3392 reader-visible items on 2026-08-29.
    expect(showsHeatBadge(0)).toBe(false);
    expect(showsHeatBadge(0.007)).toBe(false);
    expect(showsHeatBadge(0.49)).toBe(false);
  });

  it("hides it just below the rounding boundary and shows it just above", () => {
    expect(showsHeatBadge(0.499)).toBe(false);
    expect(showsHeatBadge(0.5)).toBe(true);
  });

  it("shows the badge once there is a number worth reading", () => {
    expect(showsHeatBadge(1)).toBe(true);
    expect(showsHeatBadge(39.85)).toBe(true);
  });

  it("treats a missing score as no badge rather than as zero", () => {
    expect(showsHeatBadge(null)).toBe(false);
    expect(showsHeatBadge(undefined)).toBe(false);
  });
});

describe("heatBadge", () => {
  it("is an integer, matching what the panels show", () => {
    expect(heatBadge(0.5)).toBe("1");
    expect(heatBadge(13.125)).toBe("13");
  });
});

describe("heatStat", () => {
  it("keeps one decimal below the threshold so a label never reads as zero", () => {
    // A labelled row can carry a small number; "当前热度 0" looks like the score
    // failed to compute, "当前热度 0.2" is a reading.
    expect(heatStat(0.21)).toBe("0.2");
    expect(heatStat(0)).toBe("0.0");
  });

  it("agrees with the badge above the threshold", () => {
    expect(heatStat(11.98)).toBe(heatBadge(11.98));
    expect(heatStat(1)).toBe(heatBadge(1));
  });

  it("renders a dash when there is no score at all", () => {
    expect(heatStat(null)).toBe("—");
    expect(heatStat(undefined)).toBe("—");
  });
});

describe("call sites", () => {
  /**
   * The defect this module exists for was drift, not arithmetic: the item card,
   * the story list and the story detail page each rounded the score themselves,
   * so fixing one left the other two rendering "0". A grep is the only thing
   * that stops the fourth copy.
   */
  it("no component rounds a heat score on its own", () => {
    const root = join(process.cwd(), "src");
    const offenders: string[] = [];

    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(path);
          continue;
        }
        if (!entry.name.endsWith(".tsx")) continue;
        const source = readFileSync(path, "utf8");
        for (const line of source.split("\n")) {
          if (/Math\.round\([^)]*(heat|hotScore)/i.test(line)) {
            offenders.push(`${path}: ${line.trim()}`);
          }
        }
      }
    };
    walk(root);

    expect(offenders, "use showsHeatBadge / heatBadge / heatStat from @/lib/heat").toEqual(
      [],
    );
  });
});

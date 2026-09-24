import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import gate from "@/data/release-gate.json";

/**
 * The /eval verdict and the CI check must read one set of thresholds.
 *
 * The page used to hold its own literals (0.85, 0.95, 0.9, 0.05) while nothing
 * that could fail a build looked at the snapshot. `scripts/check_release_gate.py`
 * now enforces the gate in CI from `release-gate.json`; a literal reappearing
 * here would let the page and CI disagree about the same release.
 */
const SOURCE = readFileSync(fileURLToPath(new URL("./page.tsx", import.meta.url)), "utf8");

describe("release gate on /eval", () => {
  it("takes every threshold from the shared gate file", () => {
    expect(SOURCE).toContain('import gate from "@/data/release-gate.json"');
    for (const key of [
      "recall_at_20_min",
      "citation_coverage_min",
      "support_supported_min",
      "presupposition_asserted_rate_max",
      "over_refusal_rate_max",
      "stochastic_refusal_causes",
      "specialist_must_pass",
    ]) {
      expect(SOURCE).toContain(`gate.${key}`);
      expect(gate).toHaveProperty(key);
    }
  });

  it("keeps no threshold literals of its own", () => {
    const verdict = SOURCE.slice(SOURCE.indexOf("const releasePassed"));
    const block = verdict.slice(0, verdict.indexOf(";"));
    expect(block).not.toMatch(/>=\s*0\.\d|<=\s*0\.\d|===\s*0\b/);
    expect(SOURCE).not.toMatch(/门槛 (85|95|90)%/);
  });
});

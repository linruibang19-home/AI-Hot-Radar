import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  fileURLToPath(new URL("./ReportWorkspace.tsx", import.meta.url)),
  "utf8",
);

describe("report workspace", () => {
  it("keeps daily, weekly, and monthly in one archive reader", () => {
    expect(SOURCE).toContain("REPORT_PERIODS.map");
    expect(SOURCE).toContain('aria-label="报告档案"');
    expect(SOURCE).toContain('aria-current={current ? "page" : undefined}');
  });

  it("renders the structured read model instead of generated markdown", () => {
    expect(SOURCE).toContain("report.sections.map");
    expect(SOURCE).toContain("section.items.map");
    expect(SOURCE).not.toContain("bodyMarkdown");
    expect(SOURCE).not.toContain("dangerouslySetInnerHTML");
  });

  it("keeps every fact traceable to its original evidence", () => {
    expect(SOURCE).toContain('href={entry.canonicalUrl}');
    expect(SOURCE).toContain("阅读原文 ↗");
    expect(SOURCE).toContain("查看事件脉络");
    expect(SOURCE).toContain("entry.sourceName");
  });

  it("makes draft state and AI disclosure visible", () => {
    expect(SOURCE).toContain("report.status");
    expect(SOURCE).toContain("DRAFT 预览");
    expect(SOURCE).toContain("事实以原文为准");
  });

  it("adds email delivery without turning the report reader client-only", () => {
    expect(SOURCE).toContain("<ReportSubscribe period={period} />");
    expect(SOURCE).not.toContain('"use client"');
  });
});

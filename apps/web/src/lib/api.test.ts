import { describe, expect, it } from "vitest";

import {
  appendItems,
  formatStorySources,
  formatPeriodKey,
  groupByDay,
  groupReports,
  normaliseVendorRelation,
  normalisePeriod,
  reportWindow,
} from "./api";

import type { ContentItem, ReportSummary } from "./api";

function report(date: string): ReportSummary {
  return {
    date,
    title: `报告 ${date}`,
    summary: "",
    itemCount: 1,
    generatedAt: "2026-08-02T00:00:00Z",
    status: "DRAFT",
  };
}

function item(id: string, publishedAt?: string): ContentItem {
  return {
    id,
    title: id,
    canonicalUrl: `https://example.com/${id}`,
    publishedAt,
    observedAt: "2026-08-02T09:00:00Z",
    source: { id: "s", name: "Source", tier: "primary" },
  };
}

describe("appendItems", () => {
  it("appends a page onto the accumulated feed", () => {
    const merged = appendItems([item("a"), item("b")], [item("c"), item("d")]);
    expect(merged.map((i) => i.id)).toEqual(["a", "b", "c", "d"]);
  });

  it("drops an item that already arrived on an earlier page", () => {
    // Ingestion runs hourly, so the feed shifts under a reader who is paging
    // through it and the same item can come back under a later cursor.
    // Concatenating blindly renders two cards with the same React key.
    const merged = appendItems([item("a"), item("b")], [item("b"), item("c")]);
    expect(merged.map((i) => i.id)).toEqual(["a", "b", "c"]);
  });

  it("keeps the position an item already had rather than moving it", () => {
    const merged = appendItems([item("a"), item("b")], [item("a")]);
    expect(merged.map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("handles an empty page without changing the feed", () => {
    const current = [item("a")];
    expect(appendItems(current, [])).toEqual(current);
  });

  it("groups appended items into the day they belong to, not a new one", () => {
    // The bug this whole component exists to fix: page two used to render its
    // own "8月3日" header because each page was grouped in isolation.
    const merged = appendItems(
      [item("a", "2026-08-03T14:00:00Z")],
      [item("b", "2026-08-03T02:00:00Z")],
    );
    const days = [...groupByDay(merged).keys()];
    expect(days).toHaveLength(1);
    expect(groupByDay(merged).get(days[0])).toHaveLength(2);
  });
});

describe("formatStorySources", () => {
  it("shows the concrete publishers behind a multi-source event", () => {
    expect(formatStorySources(["NVIDIA", "Ollama"])).toBe("NVIDIA · Ollama");
  });

  it("keeps long source lists compact without hiding the total", () => {
    expect(formatStorySources(["A", "B", "C", "D"], 3)).toBe(
      "A · B · C 等 4 个来源",
    );
  });
});

describe("normaliseVendorRelation", () => {
  it("accepts only the three public relation tiers", () => {
    expect(normaliseVendorRelation("primary")).toBe("primary");
    expect(normaliseVendorRelation("related")).toBe("related");
    expect(normaliseVendorRelation("mention")).toBe("mention");
  });

  it("fails closed to the high-precision primary tier", () => {
    expect(normaliseVendorRelation("all")).toBe("primary");
    expect(normaliseVendorRelation()).toBe("primary");
  });
});

describe("normalisePeriod", () => {
  it("accepts the three supported periods", () => {
    expect(normalisePeriod("weekly")).toBe("weekly");
    expect(normalisePeriod("monthly")).toBe("monthly");
    expect(normalisePeriod("daily")).toBe("daily");
  });

  it("falls back to daily for anything else", () => {
    // The route uses this to decide whether a URL is valid, so an unknown value
    // must land on a known period rather than reaching the API.
    expect(normalisePeriod("quarterly")).toBe("daily");
    expect(normalisePeriod(undefined)).toBe("daily");
    expect(normalisePeriod("")).toBe("daily");
  });
});

describe("formatPeriodKey", () => {
  it("spells out a daily key", () => {
    expect(formatPeriodKey("daily", "2026-08-01")).toBe("2026 年 8 月 1 日");
  });

  it("renders an ISO week as a week number", () => {
    expect(formatPeriodKey("weekly", "2026-W31")).toBe("2026 年第 31 周");
  });

  it("renders a month key without a leading zero", () => {
    expect(formatPeriodKey("monthly", "2026-08")).toBe("2026 年 8 月");
  });

  it("returns a malformed week key unchanged rather than inventing a date", () => {
    expect(formatPeriodKey("weekly", "garbage")).toBe("garbage");
  });
});

describe("reportWindow", () => {
  it("resolves an ISO week to its inclusive Monday to Sunday range", () => {
    expect(reportWindow("weekly", "2026-W32")).toBe("2026-08-03 — 2026-08-09");
  });

  it("uses the actual last day of a month", () => {
    expect(reportWindow("monthly", "2026-02")).toBe("2026-02-01 — 2026-02-28");
    expect(reportWindow("monthly", "2024-02")).toBe("2024-02-01 — 2024-02-29");
  });

  it("keeps a daily key unchanged", () => {
    expect(reportWindow("daily", "2026-08-11")).toBe("2026-08-11");
  });
});

describe("groupReports", () => {
  it("groups daily reports by month", () => {
    const groups = groupReports("daily", [
      report("2026-08-02"),
      report("2026-08-01"),
      report("2026-07-31"),
    ]);
    expect([...groups.keys()]).toEqual(["2026 年 8 月", "2026 年 7 月"]);
    expect(groups.get("2026 年 8 月")).toHaveLength(2);
  });

  it("groups weekly reports by year, not by a month they do not have", () => {
    // Slicing YYYY-MM out of "2026-W31" produced the heading "2026 年 W3 月".
    const groups = groupReports("weekly", [report("2026-W31"), report("2026-W30")]);
    expect([...groups.keys()]).toEqual(["2026 年"]);
  });

  it("groups monthly reports by year", () => {
    const groups = groupReports("monthly", [report("2026-08"), report("2025-12")]);
    expect([...groups.keys()]).toEqual(["2026 年", "2025 年"]);
  });

  it("preserves the order the API returned", () => {
    const groups = groupReports("daily", [report("2026-08-02"), report("2026-08-01")]);
    expect(groups.get("2026 年 8 月")?.map((r) => r.date)).toEqual([
      "2026-08-02",
      "2026-08-01",
    ]);
  });
});

describe("groupByDay", () => {
  it("buckets items by the local publication day", () => {
    // All three are 2026-08-02 in Asia/Shanghai: 23:00Z on the 1st is 07:00 on
    // the 2nd in Beijing. Bucketing by the UTC date split them across two
    // headings and put the newest-looking section in the wrong place.
    const groups = groupByDay([
      item("a", "2026-08-02T10:00:00Z"),
      item("b", "2026-08-02T08:00:00Z"),
      item("c", "2026-08-01T23:00:00Z"),
    ]);
    expect([...groups.keys()]).toEqual(["2026-08-02"]);
    expect(groups.get("2026-08-02")).toHaveLength(3);
  });

  it("separates days that really are different locally", () => {
    const groups = groupByDay([
      item("a", "2026-08-02T10:00:00Z"), // 18:00 on the 2nd
      item("b", "2026-08-01T10:00:00Z"), // 18:00 on the 1st
    ]);
    expect([...groups.keys()]).toEqual(["2026-08-02", "2026-08-01"]);
  });

  it("falls back to the observation time when publication is unknown", () => {
    // Items without a publication date must still appear; dropping them would
    // silently hide content that was ingested correctly.
    const groups = groupByDay([item("a")]);
    expect([...groups.keys()]).toEqual(["2026-08-02"]);
  });
});

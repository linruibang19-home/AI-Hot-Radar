import { describe, expect, it } from "vitest";

import {
  DISPLAY_TIMEZONE,
  dayKey,
  formatDate,
  formatDateTime,
  formatShortDateTime,
  formatTime,
  formatWeekday,
} from "./datetime";

describe("display timezone", () => {
  it("defaults to Asia/Shanghai", () => {
    expect(DISPLAY_TIMEZONE).toBe("Asia/Shanghai");
  });
});

describe("formatTime", () => {
  it("renders the local clock, not UTC", () => {
    // The bug this replaces: an article published at 16:25 Beijing time was
    // shown as "08:25", so an afternoon of news read as though nothing had
    // arrived since morning.
    expect(formatTime("2026-08-03T08:25:00Z")).toBe("16:25");
  });

  it("handles a timestamp that already carries an offset", () => {
    expect(formatTime("2026-08-03T16:25:00+08:00")).toBe("16:25");
  });

  it("renders midnight as 00:00, not 24:00", () => {
    expect(formatTime("2026-08-02T16:00:00Z")).toBe("00:00");
  });

  it("returns a placeholder for missing or unparseable input", () => {
    expect(formatTime(undefined)).toBe("--:--");
    expect(formatTime(null)).toBe("--:--");
    expect(formatTime("not a date")).toBe("--:--");
  });
});

describe("dayKey", () => {
  it("uses the local calendar date", () => {
    expect(dayKey("2026-08-03T08:25:00Z")).toBe("2026-08-03");
  });

  it("rolls to the next day past 16:00 UTC", () => {
    // 2026-08-03T16:30Z is already 2026-08-04 in Beijing. Slicing the ISO
    // string filed it under the 3rd, so late-evening items landed in the wrong
    // day section.
    expect(dayKey("2026-08-03T16:30:00Z")).toBe("2026-08-04");
  });

  it("keeps the same day just before the boundary", () => {
    expect(dayKey("2026-08-03T15:59:00Z")).toBe("2026-08-03");
  });

  it("returns null rather than a fake date", () => {
    expect(dayKey(undefined)).toBeNull();
    expect(dayKey("")).toBeNull();
    expect(dayKey("garbage")).toBeNull();
  });
});

describe("formatWeekday", () => {
  it("names the weekday of a display-timezone key", () => {
    expect(formatWeekday("2026-08-03")).toBe("周一");
  });

  it("does not shift the key it is given", () => {
    // The key already carries the display-timezone date; converting it again
    // would move it back a day.
    expect(formatWeekday("2026-08-04")).toBe("周二");
  });

  it("returns empty for a malformed key", () => {
    expect(formatWeekday("nope")).toBe("");
  });
});

describe("formatDateTime", () => {
  it("renders date and time in the display timezone", () => {
    expect(formatDateTime("2026-08-03T09:12:53Z")).toBe("2026-08-03 17:12");
  });

  it("crosses the date boundary correctly", () => {
    expect(formatDateTime("2026-08-03T16:30:00Z")).toBe("2026-08-04 00:30");
  });

  it("falls back to a dash", () => {
    expect(formatDateTime(null)).toBe("—");
  });
});

describe("formatShortDateTime", () => {
  it("drops the year for dense tables", () => {
    expect(formatShortDateTime("2026-08-03T09:12:00Z")).toBe("08-03 17:12");
  });
});

describe("formatDate", () => {
  it("returns the local calendar date", () => {
    expect(formatDate("2026-08-03T16:30:00Z")).toBe("2026-08-04");
  });

  it("says so when there is no date", () => {
    expect(formatDate(undefined)).toBe("时间未知");
  });
});

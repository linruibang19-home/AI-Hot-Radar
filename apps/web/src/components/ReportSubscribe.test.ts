import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SUBSCRIBE_SOURCE = readFileSync(
  fileURLToPath(new URL("./ReportSubscribe.tsx", import.meta.url)),
  "utf8",
);
const ACTION_SOURCE = readFileSync(
  fileURLToPath(new URL("./SubscriptionActionPanel.tsx", import.meta.url)),
  "utf8",
);

describe("report email subscription UI", () => {
  it("requires explicit period and email confirmation", () => {
    expect(SUBSCRIBE_SOURCE).toContain('type="email"');
    expect(SUBSCRIBE_SOURCE).toContain("periods.length === 0");
    expect(SUBSCRIBE_SOURCE).toContain("未经确认不会投递");
    expect(SUBSCRIBE_SOURCE).toContain("不会逐条发送动态");
    expect(SUBSCRIBE_SOURCE).toContain("不会补发确认前的历史期刊");
    expect(SUBSCRIBE_SOURCE).toContain("在线原文与退订链接");
    expect(SUBSCRIBE_SOURCE).toContain('fetch("/api/subscriptions"');
  });

  it("does not mutate subscription state merely by opening an email link", () => {
    expect(ACTION_SOURCE).toContain("async function apply()");
    expect(ACTION_SOURCE).toContain("onClick={apply}");
    expect(ACTION_SOURCE).not.toContain("useEffect");
  });

  it("keeps all three report periods and the reader timezone visible", () => {
    expect(SUBSCRIBE_SOURCE).toContain('{ value: "daily"');
    expect(SUBSCRIBE_SOURCE).toContain('{ value: "weekly"');
    expect(SUBSCRIBE_SOURCE).toContain('{ value: "monthly"');
    expect(SUBSCRIBE_SOURCE).toContain("resolvedOptions().timeZone");
  });
});

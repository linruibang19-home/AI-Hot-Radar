import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

/**
 * The ask relay, tested for the one thing that is invisible from either side.
 *
 * ai-service meters `/ask` per caller and identifies the caller from the first
 * `X-Forwarded-For` entry — that logic is correct and covered by its own tests.
 * This route sits between the browser and it, and dropped the header, so every
 * request arrived wearing the web container's address. The quota of 3/min and
 * 20/day was therefore applied to the whole site at once: two readers asking in
 * the same minute refused each other, and twenty questions closed the feature
 * for everyone until midnight.
 *
 * Neither side was wrong on its own, which is why nothing caught it. The seam
 * is the thing that needs the test.
 */

function ask(headers: Record<string, string> = {}) {
  return new Request("http://web:3000/api/ask", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify({ question: "最近有什么新模型？" }),
  });
}

function upstream(status = 200, body: unknown = { answerMarkdown: "", citations: [] }) {
  const spy = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

/** The `init` of the first upstream call — the argument these tests are about. */
function sentHeaders(spy: { mock: { calls: unknown[] } }): Record<string, string> {
  const [, init] = (spy.mock.calls[0] ?? []) as [string?, RequestInit?];
  return (init?.headers ?? {}) as Record<string, string>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the ask relay carries the caller's address", () => {
  it("forwards X-Forwarded-For so the quota is charged per reader", async () => {
    const spy = upstream();
    await POST(ask({ "x-forwarded-for": "203.0.113.7" }));

    expect(sentHeaders(spy)["x-forwarded-for"]).toBe("203.0.113.7");
  });

  it("keeps the chain intact so the original client stays first", async () => {
    // ai-service reads entry one. Rewriting the chain to just the nearest hop
    // would put every reader behind the proxy into one bucket again.
    const spy = upstream();
    await POST(ask({ "x-forwarded-for": "203.0.113.7, 10.0.0.2" }));

    expect(sentHeaders(spy)["x-forwarded-for"]).toBe("203.0.113.7, 10.0.0.2");
  });

  it("falls back to X-Real-IP when that is the only one present", async () => {
    const spy = upstream();
    await POST(ask({ "x-real-ip": "203.0.113.9" }));

    expect(sentHeaders(spy)["x-forwarded-for"]).toBe("203.0.113.9");
  });

  it("sends no address at all when there is no proxy", async () => {
    // Local development has no proxy and no header. Inventing one would put a
    // fabricated address into a rate-limit bucket.
    const spy = upstream();
    await POST(ask());

    expect(sentHeaders(spy)["x-forwarded-for"]).toBeUndefined();
  });
});

describe("a quota refusal reaches the reader as one", () => {
  it("relays the 429 and its reason rather than a generic failure", async () => {
    const spy = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "今日提问次数已用完，请明天再来。" }), {
          status: 429,
          headers: { "content-type": "application/json", "retry-after": "3600" },
        }),
    );
    vi.stubGlobal("fetch", spy);

    const response = await POST(ask());
    const body = (await response.json()) as { error: string };

    // 502 with "请稍后重试" told the reader to do the one thing that cannot
    // work, and hid the fact that a limit exists at all.
    expect(response.status).toBe(429);
    expect(body.error).toContain("今日提问次数已用完");
    expect(response.headers.get("retry-after")).toBe("3600");
  });

  it("still reports a provider outage as an outage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));

    const response = await POST(ask());
    const body = (await response.json()) as { error: string };

    expect(response.status).toBe(502);
    expect(body.error).toContain("模型服务");
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";

import { proxySubscription } from "./subscription-proxy";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("subscription proxy", () => {
  it("relays a same-origin request to the internal Core API", async () => {
    const fetchSpy = vi.fn(async (...args: Parameters<typeof fetch>) => {
      void args;
      return Response.json({ status: "PENDING_CONFIRMATION" }, { status: 202 });
    });
    vi.stubGlobal("fetch", fetchSpy);
    const request = new Request("http://web:3000/api/subscriptions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        email: "reader@example.com",
        periods: ["daily"],
        timezone: "Asia/Shanghai",
      }),
    });

    const response = await proxySubscription(request);

    expect(response.status).toBe(202);
    expect(fetchSpy).toHaveBeenCalledOnce();
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/api/v1/subscriptions");
  });

  it("preserves confirmation errors and never caches token responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "invalid" }, { status: 400 })),
    );
    const request = new Request("http://web:3000/api/subscriptions/confirm", {
      method: "POST",
      body: JSON.stringify({ token: "invalid" }),
    });

    const response = await proxySubscription(request, "/confirm");

    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("rejects oversized bodies before contacting Core API", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const request = new Request("http://web:3000/api/subscriptions", {
      method: "POST",
      headers: { "content-length": "20000" },
      body: "{}",
    });

    const response = await proxySubscription(request);

    expect(response.status).toBe(413);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

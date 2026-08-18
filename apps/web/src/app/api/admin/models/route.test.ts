import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { POST } from "./route";

function request(body: object, origin = "http://web:3000") {
  return new NextRequest("http://web:3000/api/admin/models", {
    method: "POST",
    headers: { "content-type": "application/json", origin },
    body: JSON.stringify(body),
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("generation model mutation relay", () => {
  it("rejects cross-origin attempts before credentials are read", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const response = await POST(request({}, "https://attacker.example"));
    expect(response.status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("forwards the operator token only as an authorization header", async () => {
    const fetchSpy = vi.fn(async (_url: string, init: RequestInit) => {
      expect((init.headers as Record<string, string>).Authorization).toBe("Bearer one-use-token");
      expect((init.headers as Record<string, string>)["X-Confirm-Target"]).toBe(
        "deepseek-v4-pro",
      );
      expect(init.body).not.toContain("one-use-token");
      return new Response(
        JSON.stringify({ current: { model_id: "deepseek-v4-pro", version: 2 } }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchSpy);

    const response = await POST(
      request({
        modelId: "deepseek-v4-pro",
        confirm: "deepseek-v4-pro",
        token: "one-use-token",
        reason: "compare quality",
      }),
    );

    expect(response.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledOnce();
  });

  it("accepts the browser origin represented by the forwarded public host", async () => {
    // Behind Caddy the container's own origin is not the browser's, so
    // comparing against `nextUrl.origin` alone would reject every real request.
    const fetchSpy = vi.fn(async () =>
      new Response(JSON.stringify({ baseUrl: "https://api.deepseek.com" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const incoming = request(
      { action: "provider", baseUrl: "https://api.deepseek.com", apiKey: "sk-k", token: "op" },
      "https://aihotradar.online",
    );
    incoming.headers.set("x-forwarded-host", "aihotradar.online");
    incoming.headers.set("x-forwarded-proto", "https");

    expect((await POST(incoming)).status).toBe(200);
  });

  it("echoes the address it is about to store", async () => {
    const fetchSpy = vi.fn(async (url: string, init: RequestInit) => {
      expect(url).toContain("/api/v1/admin/models/provider");
      expect((init.headers as Record<string, string>)["X-Confirm-Target"]).toBe(
        "https://api.deepseek.com",
      );
      // The operator credential is a header; the provider key is the body. They
      // must never swap places.
      expect(init.body).not.toContain("one-use-token");
      expect(init.body).toContain("sk-provider");
      return new Response(JSON.stringify({ baseUrl: "https://api.deepseek.com" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    const response = await POST(
      request({
        action: "provider",
        baseUrl: " https://api.deepseek.com ",
        apiKey: " sk-provider\r\n",
        token: "one-use-token",
      }),
    );

    expect(response.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledOnce();
  });

  it("rejects a model id typed into the address field before any call", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const response = await POST(
      request({ action: "provider", baseUrl: "deepseek-v4-pro", apiKey: "sk", token: "op" }),
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: "invalid_provider_url" });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("routes the reset action to its own endpoint with a fixed echo", async () => {
    const fetchSpy = vi.fn(async (url: string, init: RequestInit) => {
      expect(url).toContain("/api/v1/admin/models/provider/reset");
      expect((init.headers as Record<string, string>)["X-Confirm-Target"]).toBe("environment");
      return new Response(JSON.stringify({ usesEnvironment: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    expect((await POST(request({ action: "provider-reset", token: "op" }))).status).toBe(200);
  });

  it("refuses without an operator credential before anything leaves the process", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const response = await POST(
      request({ action: "provider", baseUrl: "https://api.deepseek.com", apiKey: "sk" }),
    );

    expect(response.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

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
});

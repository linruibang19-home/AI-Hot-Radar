const API_BASE_URL = process.env.API_BASE_URL ?? "http://core-api:8080";
const MAX_BODY_BYTES = 16_384;

export async function proxySubscription(request: Request, suffix = ""): Promise<Response> {
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
    return Response.json({ detail: "request body is too large" }, { status: 413 });
  }

  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) {
    return Response.json({ detail: "request body is too large" }, { status: 413 });
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}/api/v1/subscriptions${suffix}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const responseBody = await upstream.text();
    return new Response(responseBody, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  } catch {
    return Response.json(
      { detail: "订阅服务暂时不可用，请稍后重试。" },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}

import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://core-api:8080";
const ALLOWED_MODELS = new Set(["deepseek-v4-flash", "deepseek-v4-pro"]);

type Action = "select" | "provider" | "provider-reset";

interface AdminModelBody {
  action?: Action;
  token?: string;
  modelId?: string;
  confirm?: string;
  reason?: string;
  baseUrl?: string;
  apiKey?: string;
}

interface Upstream {
  path: string;
  confirm: string;
  body?: object;
}

/**
 * Which upstream call this request means, and what it must echo.
 *
 * Validated here rather than relayed blindly: the browser never reaches
 * core-api directly, so this is the only place that can reject a malformed
 * request before an operator credential is put on the wire.
 */
function plan(body: AdminModelBody): Upstream | { error: string } {
  const action = body.action ?? "select";

  if (action === "provider-reset") {
    return { path: "/api/v1/admin/models/provider/reset", confirm: "environment" };
  }

  if (action === "provider") {
    // Trimmed before anything else: password managers and chat clients paste a
    // trailing newline into key fields, and a provider rejects the result as a
    // bad credential rather than as a formatting problem.
    const baseUrl = body.baseUrl?.trim() ?? "";
    const apiKey = body.apiKey?.trim() ?? "";
    if (!baseUrl) return { error: "invalid_provider_url" };
    try {
      if (!["http:", "https:"].includes(new URL(baseUrl).protocol)) {
        return { error: "invalid_provider_url" };
      }
    } catch {
      return { error: "invalid_provider_url" };
    }
    return {
      path: "/api/v1/admin/models/provider",
      confirm: baseUrl,
      body: { baseUrl, apiKey },
    };
  }

  const modelId = body.modelId?.trim() ?? "";
  if (!ALLOWED_MODELS.has(modelId) || (body.confirm?.trim() ?? "") !== modelId) {
    return { error: "invalid_selection" };
  }
  return {
    path: `/api/v1/admin/models/generation/${encodeURIComponent(modelId)}/select`,
    confirm: modelId,
    body: { reason: (body.reason ?? "").slice(0, 300) },
  };
}

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (origin && !isSameOrigin(request, origin)) {
    return NextResponse.json({ error: "cross_origin_rejected" }, { status: 403 });
  }

  let body: AdminModelBody;
  try {
    body = (await request.json()) as AdminModelBody;
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }

  const token = body.token?.trim() ?? "";
  if (!token) {
    return NextResponse.json({ error: "operator_credential_required" }, { status: 400 });
  }

  const upstream = plan(body);
  if ("error" in upstream) {
    return NextResponse.json({ error: upstream.error }, { status: 400 });
  }

  try {
    const response = await fetch(`${API_BASE_URL}${upstream.path}`, {
      method: "POST",
      cache: "no-store",
      headers: {
        // The operator credential travels as a header and never as body content,
        // so it cannot end up in a request log that records payloads.
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Confirm-Target": upstream.confirm,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify(upstream.body ?? {}),
    });
    const payload = (await response.json().catch(() => ({ error: "upstream_error" }))) as object;
    return NextResponse.json(payload, {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: "core_api_unreachable" }, { status: 503 });
  }
}

/**
 * Same-origin behind a proxy.
 *
 * `request.nextUrl.origin` is the container's own address, so comparing against
 * it alone rejects every real browser request once Caddy is in front.
 */
function isSameOrigin(request: NextRequest, origin: string) {
  try {
    const supplied = new URL(origin);
    // Forwarded host first, then the real one, then the URL's own — a direct
    // request carries no Host header of its own in this runtime, and treating
    // that as a mismatch would reject every same-origin call without a proxy.
    const host =
      request.headers.get("x-forwarded-host")?.split(",")[0]?.trim() ||
      request.headers.get("host") ||
      request.nextUrl.host;
    if (!host) return false;
    const protocol =
      request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim() ||
      request.nextUrl.protocol.replace(":", "");
    return supplied.origin === `${protocol}://${host}`;
  } catch {
    return false;
  }
}

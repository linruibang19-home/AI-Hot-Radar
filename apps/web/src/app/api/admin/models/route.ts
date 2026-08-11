import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://core-api:8080";
const ALLOWED_MODELS = new Set(["deepseek-v4-flash", "deepseek-v4-pro"]);

interface SelectionBody {
  modelId?: string;
  token?: string;
  confirm?: string;
  reason?: string;
}

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return NextResponse.json({ error: "cross_origin_rejected" }, { status: 403 });
  }

  let body: SelectionBody;
  try {
    body = (await request.json()) as SelectionBody;
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }

  const modelId = body.modelId?.trim() ?? "";
  const token = body.token?.trim() ?? "";
  const confirm = body.confirm?.trim() ?? "";
  if (!ALLOWED_MODELS.has(modelId) || confirm !== modelId || !token) {
    return NextResponse.json({ error: "invalid_selection" }, { status: 400 });
  }

  try {
    const upstream = await fetch(
      `${API_BASE_URL}/api/v1/admin/models/generation/${encodeURIComponent(modelId)}/select`,
      {
        method: "POST",
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          "X-Confirm-Target": modelId,
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ reason: (body.reason ?? "").slice(0, 300) }),
      },
    );
    const payload = (await upstream.json().catch(() => ({ error: "upstream_error" }))) as object;
    return NextResponse.json(payload, {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: "core_api_unreachable" }, { status: 503 });
  }
}

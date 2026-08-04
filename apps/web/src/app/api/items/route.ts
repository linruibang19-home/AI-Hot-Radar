import { NextResponse } from "next/server";

import { fetchItems } from "@/lib/api";

/**
 * Browser-facing proxy for the item feed.
 *
 * The feed's "load more" runs in the browser, and the browser cannot reach
 * core-api: `API_BASE_URL` is `http://core-api:8080`, a name that only resolves
 * inside the Compose network. Exposing core-api to the host instead would put
 * an unauthenticated admin surface on a public port, so the request is relayed
 * here and the internal address stays internal.
 */

export const dynamic = "force-dynamic";

const MAX_LIMIT = 50;

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;

  const requested = Number(params.get("limit") ?? 25);
  const limit = Number.isFinite(requested)
    ? Math.min(Math.max(Math.trunc(requested), 1), MAX_LIMIT)
    : 25;

  const page = await fetchItems({
    limit,
    cursor: params.get("cursor") ?? undefined,
    q: params.get("q") ?? undefined,
    contentType: params.get("contentType") ?? undefined,
    day: params.get("day") ?? undefined,
  });

  return NextResponse.json(page, {
    // The feed changes hourly and the caller is paginating through it; a cached
    // page here would hand out stale cursors.
    headers: { "cache-control": "no-store" },
  });
}

import { NextResponse } from "next/server";

/**
 * One stored conversation, by id.
 *
 * Same reason as the sibling route: ai-service is only reachable inside the
 * Compose network, so the browser talks to Next and Next talks to it.
 *
 * Unlike `POST /api/ask` this costs nothing upstream — it replays a row — so it
 * is not rate limited. A permalink that refused the person it was shared with
 * would not be a permalink.
 */

export const dynamic = "force-dynamic";

const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://ai-service:8000";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;

  try {
    const response = await fetch(`${AI_SERVICE_URL}/rag/query/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    if (response.status === 404) {
      return NextResponse.json({ error: "not found" }, { status: 404 });
    }
    if (!response.ok) {
      return NextResponse.json({ error: "unavailable" }, { status: 502 });
    }
    return NextResponse.json(await response.json(), {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: "unavailable" }, { status: 502 });
  }
}

import { NextResponse } from "next/server";

const REQUEST_ID_HEADER = "X-Request-ID";

/**
 * Liveness endpoint for the web tier.
 *
 * Dependency-free by design: the web app renders through core-api, so a
 * database outage is core-api's readiness concern, not a reason to report the
 * Next.js process as dead.
 */
export async function GET(request: Request): Promise<NextResponse> {
  const requestId = request.headers.get(REQUEST_ID_HEADER) ?? crypto.randomUUID();

  return NextResponse.json(
    { status: "ok", service: "web" },
    { headers: { [REQUEST_ID_HEADER]: requestId } },
  );
}

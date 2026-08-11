import { proxySubscription } from "@/lib/subscription-proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return proxySubscription(request, "/unsubscribe");
}

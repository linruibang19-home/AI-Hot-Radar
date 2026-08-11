import type { Metadata } from "next";

import { SubscriptionActionPanel } from "@/components/SubscriptionActionPanel";

export const metadata: Metadata = { title: "确认邮件订阅", robots: { index: false, follow: false } };

export default async function ConfirmSubscriptionPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token = "" } = await searchParams;
  return <SubscriptionActionPanel action="confirm" token={token} />;
}

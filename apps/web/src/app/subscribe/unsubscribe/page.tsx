import type { Metadata } from "next";

import { SubscriptionActionPanel } from "@/components/SubscriptionActionPanel";

export const metadata: Metadata = { title: "取消邮件订阅", robots: { index: false, follow: false } };

export default async function UnsubscribePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token = "" } = await searchParams;
  return <SubscriptionActionPanel action="unsubscribe" token={token} />;
}

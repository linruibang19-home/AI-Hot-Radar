import Link from "next/link";

import { HotList } from "@/components/HotList";
import { fetchHot } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "热点榜",
  description: "按时效、来源权重与独立信源数排序的 AI 热点榜。",
};

export const dynamic = "force-dynamic";

export default async function HotPage() {
  const items = await fetchHot(30);

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">热点榜</h1>
        {/* 原文是完整的热度公式加一段它与质量分的辨析。那属于文档，见
            docs/spec；副标题只需要让人知道这一页按什么排。 */}
        <p className="page-subtitle">越新、越多信源报道的越靠前，热度随时间衰减</p>
      </header>

      {items.length === 0 ? (
        <div className="empty">
          尚未计算热度。请先运行：
          <br />
          <code>docker compose exec ai-service python -m ahr.cli heat</code>
        </div>
      ) : (
        <HotList items={items} limit={30} showMore={false} />
      )}

      <div className="notice">
        「独立信源数」现在取自<strong>事件聚类</strong>——同一事件下有多少家不同信源报道过，
        而不再是近似重复分组。多数条目仍为 1，因为大多数发布确实只有官方一个来源；
        被多家媒体跟进的事件会因此排到前面。
        事件聚类由算法自动完成，可能存在误合或漏合，具体归并见
        <Link href="/stories">事件追踪</Link>。
      </div>
    </>
  );
}

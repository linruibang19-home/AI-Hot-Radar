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
        <p className="page-subtitle">
          热度 = 时效衰减 × 内容类型权重 ×（来源等级 + 独立信源 + 质量），与质量分是两回事：
          质量分评价单篇文章且一经计算即稳定，热度衡量一件事当前受到多少关注并随时间衰减
        </p>
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
        <Link href="/stories">事件聚合</Link>。
      </div>
    </>
  );
}

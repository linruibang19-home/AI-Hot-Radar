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
        当前的「独立信源数」由近似重复分组近似得出，绝大多数条目为 1。
        真正的多源验证需要事件聚类，因此这份榜单目前是
        <strong>编辑意义上的合理排序</strong>，而不是「多少家媒体报道了同一件事」的真实热度。
      </div>
    </>
  );
}

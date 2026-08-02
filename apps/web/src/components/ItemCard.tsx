import Link from "next/link";

import type { ContentItem } from "@/lib/api";

const CONTENT_TYPE_LABELS: Record<string, string> = {
  model_release: "模型发布",
  product_release: "产品发布",
  api_update: "API 更新",
  research: "研究",
  open_source: "开源",
  business: "商业",
  policy: "政策",
  security: "安全",
  opinion: "观点",
  tutorial: "教程",
};

function formatTime(value?: string): string {
  if (!value) return "";
  return value.slice(11, 16);
}

export function ItemCard({
  item,
  selectionReason,
  selectionScore,
}: {
  item: ContentItem;
  selectionReason?: string;
  selectionScore?: number;
}) {
  // Prefer the Chinese title, but fall back to the original so an article that
  // has not been enriched yet is still readable (M2 acceptance).
  const title = item.zhTitle ?? item.title;
  const body = item.summary ?? item.excerpt;

  return (
    <article className="card">
      <div className="card-meta">
        <span>{formatTime(item.publishedAt ?? item.observedAt)}</span>
        <span>·</span>
        <span>{item.source.name}</span>
        {item.source.tier === "primary" && <span className="tag tag-primary">一手来源</span>}
        {item.contentType && (
          <span className="tag">{CONTENT_TYPE_LABELS[item.contentType] ?? item.contentType}</span>
        )}
        {typeof item.qualityScore === "number" && (
          <span className="tag">质量 {Math.round(item.qualityScore)}</span>
        )}
        {typeof selectionScore === "number" && (
          <span className="tag tag-primary">精选 {Math.round(selectionScore)}</span>
        )}
      </div>

      <h3 className="card-title">
        <Link href={`/items/${item.id}`}>{title}</Link>
      </h3>

      {body && <p className="card-summary">{body.slice(0, 180)}</p>}

      {/* AHR-PRD-100 §4: the UI must explain why an item was chosen. */}
      {selectionReason && <p className="card-reason">入选理由：{selectionReason}</p>}
    </article>
  );
}

export { CONTENT_TYPE_LABELS };

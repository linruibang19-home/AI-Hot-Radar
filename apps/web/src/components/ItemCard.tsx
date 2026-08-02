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

export function ItemCard({
  item,
  selectionReason,
  curated = false,
}: {
  item: ContentItem;
  selectionReason?: string;
  curated?: boolean;
}) {
  // Prefer the Chinese title, but fall back to the original so an article that
  // has not been enriched yet is still readable (M2 acceptance).
  const title = item.zhTitle ?? item.title;
  const body = item.summary ?? item.excerpt;
  const others = (item.independentSources ?? 1) - 1;

  return (
    <article className="card">
      <header className="card-head">
        <span className="card-source">{item.source.name}</span>
        {item.source.tier === "primary" && <span className="tag tag-primary">一手来源</span>}
        {curated && <span className="tag tag-curated">✦ 精选</span>}
        {item.contentType && (
          <span className="tag">{CONTENT_TYPE_LABELS[item.contentType] ?? item.contentType}</span>
        )}
        {typeof item.hotScore === "number" && (
          // Rounded and unlabelled: hot_score is unbounded and decays
          // continuously, so decimals would imply precision it does not have.
          <span className="card-heat" title="热度">
            <span className="card-heat-dot" aria-hidden="true" />
            {Math.round(item.hotScore)}
          </span>
        )}
      </header>

      <h3 className="card-title">
        <Link href={`/items/${item.id}`}>{title}</Link>
      </h3>

      {body && <p className="card-summary">{body.slice(0, 180)}</p>}

      {others > 0 && <p className="card-corroboration">另有 {others} 家信源报道</p>}

      {/* AHR-PRD-100 §4: the UI must explain why an item was chosen. */}
      {selectionReason && (
        <p className="card-reason">
          <span className="card-reason-label">推荐理由</span>
          {selectionReason}
        </p>
      )}
    </article>
  );
}

export { CONTENT_TYPE_LABELS };

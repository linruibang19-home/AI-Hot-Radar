import { formatDate } from "@/lib/datetime";
import Link from "next/link";

import { CONTENT_TYPE_LABELS } from "@/components/ItemCard";
import { fetchStories, formatStorySources } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "事件追踪",
  description: "把同一事件的多方报道放在一起，优先核验主来源并查看来源时间线。",
};

export const dynamic = "force-dynamic";

export default async function StoriesPage() {
  // A one-item Story is an internal grouping identity, not a separate reader
  // experience. The public page only exposes events that actually have more
  // than one independent publisher behind them.
  const stories = await fetchStories(50);

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">事件追踪</h1>
        <p className="page-subtitle">同一件事只占一条，展开可对照各家报道</p>
      </header>

      <div className="story-purpose">
        <strong>怎么看：</strong>先读标记为主来源的原始材料，再用其他报道补充背景、采用情况或
        不同视角。单篇资讯仍保留在“全部 AI 动态”，不会伪装成多来源事件。
      </div>

      {stories.length === 0 ? (
        <div className="empty">
          暂无通过高置信度门槛的多来源事件。单篇内容请前往“全部 AI 动态”。
        </div>
      ) : (
        stories.map((story) => (
          <article className="card" key={story.id}>
            <header className="card-head">
              <span className="card-source">{story.primarySourceName ?? "未知来源"}</span>
              {story.primarySourceTier === "primary" && (
                <span className="tag tag-primary">一手来源</span>
              )}
              {story.contentType && (
                <span className="tag">
                  {CONTENT_TYPE_LABELS[story.contentType] ?? story.contentType}
                </span>
              )}
              {story.locked && <span className="tag">已锁定</span>}
              <span className="card-heat">
                <span className="card-heat-dot" aria-hidden="true" />
                {Math.round(story.heat ?? 0)}
              </span>
            </header>

            <h2 className="card-title">
              <Link href={`/stories/${story.slug}`}>{story.title}</Link>
            </h2>

            <p className="card-corroboration">
              {formatDate(story.occurredAt)} · {story.itemCount} 篇报道 ·{" "}
              <strong>{story.independentSources}</strong> 家独立信源
            </p>
            <p className="story-source-list">
              <span>参与来源</span>
              {formatStorySources(story.sourceNames)}
            </p>
          </article>
        ))
      )}
    </>
  );
}

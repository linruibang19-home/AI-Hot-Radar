import { formatDate } from "@/lib/datetime";
import Link from "next/link";

import { CONTENT_TYPE_LABELS } from "@/components/ItemCard";
import { fetchStories } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "事件聚合",
  description: "同一事件的多方报道聚合，标注主来源与独立信源数。",
};

export const dynamic = "force-dynamic";

export default async function StoriesPage({
  searchParams,
}: {
  searchParams: Promise<{ all?: string }>;
}) {
  const params = await searchParams;
  // Default to corroborated events only: a "story" of one item is just an
  // article, and listing 490 of them would bury the seven that are real events.
  const minSources = params.all === "1" ? 1 : 2;
  const stories = await fetchStories(50, minSources);

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">事件聚合</h1>
        <p className="page-subtitle">
          同一件事的多方报道会聚成一个事件，标注主来源与独立信源数 ·
          主来源按「官方当事方 &gt; 官方文档/仓库 &gt; 论文 &gt; 权威媒体 &gt; 技术作者」选出
        </p>
      </header>

      <nav className="tabs" aria-label="事件筛选">
        <Link href="/stories" className={minSources === 2 ? "tab tab-active" : "tab"}>
          多信源事件
        </Link>
        <Link href="/stories?all=1" className={minSources === 1 ? "tab tab-active" : "tab"}>
          全部事件
        </Link>
      </nav>

      {stories.length === 0 ? (
        <div className="empty">
          尚未聚类。请先运行：
          <br />
          <code>docker compose exec ai-service python -m ahr.cli cluster</code>
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
          </article>
        ))
      )}
    </>
  );
}

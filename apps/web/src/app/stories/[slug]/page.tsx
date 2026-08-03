import { formatDate, formatDateTime } from "@/lib/datetime";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CONTENT_TYPE_LABELS } from "@/components/ItemCard";
import { fetchStory } from "@/lib/api";

import type { Metadata } from "next";

export const dynamic = "force-dynamic";

function formatStamp(value?: string): string {
  if (!value) return "时间未知";
  return formatDateTime(value);
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const detail = await fetchStory(slug);
  return { title: detail?.story.title ?? "事件" };
}

export default async function StoryPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const detail = await fetchStory(slug);
  if (!detail) {
    notFound();
  }

  const { story, timeline } = detail;

  return (
    <>
      <p className="page-subtitle" style={{ marginBottom: 10 }}>
        <Link href="/stories">← 返回事件列表</Link>
      </p>

      <header className="page-head">
        <h1 className="page-title">{story.title}</h1>
        <p className="page-subtitle">
          {formatDate(story.occurredAt)} ·{" "}
          {story.itemCount} 篇报道 · {story.independentSources} 家独立信源
          {story.contentType
            ? ` · ${CONTENT_TYPE_LABELS[story.contentType] ?? story.contentType}`
            : ""}
        </p>
      </header>

      <div className="stat-row">
        <div className="stat">
          <div className="stat-value">{story.independentSources}</div>
          <div className="stat-label">独立信源</div>
        </div>
        <div className="stat">
          <div className="stat-value">{story.itemCount}</div>
          <div className="stat-label">报道篇数</div>
        </div>
        <div className="stat">
          <div className="stat-value">{Math.round(story.heat ?? 0)}</div>
          <div className="stat-label">当前热度</div>
        </div>
      </div>

      <h2 className="day-heading">报道时间线</h2>

      <div className="tl-body">
        {timeline.map((entry) => (
          <div className="tl-row" key={entry.id}>
            <div className="tl-gutter">
              <time className="tl-time">{formatStamp(entry.publishedAt ?? entry.observedAt)}</time>
              <span className="tl-dot" aria-hidden="true" />
            </div>
            <div className="tl-content">
              <article className="card">
                <header className="card-head">
                  <span className="card-source">{entry.sourceName}</span>
                  {entry.relationType === "PRIMARY" && (
                    <span className="tag tag-primary">主来源</span>
                  )}
                  {entry.sourceTier === "primary" && entry.relationType !== "PRIMARY" && (
                    <span className="tag">一手</span>
                  )}
                  {typeof entry.similarity === "number" && (
                    <span className="tag" title="与主来源的聚类相似度">
                      相似度 {entry.similarity.toFixed(2)}
                    </span>
                  )}
                </header>

                <h3 className="card-title">
                  <Link href={`/items/${entry.id}`}>{entry.title}</Link>
                </h3>

                {entry.summary && <p className="card-summary">{entry.summary.slice(0, 200)}</p>}

                <p className="card-corroboration">
                  <a href={entry.canonicalUrl} target="_blank" rel="noreferrer noopener">
                    阅读原文 ↗
                  </a>
                </p>
              </article>
            </div>
          </div>
        ))}
      </div>

      <div className="notice">
        事件聚合由算法自动完成（story-v1），可能存在误合或漏合。
        主来源按信源等级选出，每篇报道均链接到原文，事实请以原文为准。
      </div>
    </>
  );
}

import { formatDateTime } from "@/lib/datetime";

import { BackLink } from "@/components/BackLink";
import { notFound } from "next/navigation";
import { CONTENT_TYPE_LABELS } from "@/components/ItemCard";
import { fetchItem } from "@/lib/api";

export const dynamic = "force-dynamic";

/** The publisher's host, or nothing. A malformed URL must not 500 the page. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export default async function ItemDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const item = await fetchItem(id);

  if (!item) {
    notFound();
  }

  return (
    <>
      <BackLink href="/items">返回全部动态</BackLink>

      <h1 className="page-title">{item.zhTitle ?? item.title}</h1>
      {item.zhTitle && item.zhTitle !== item.title && (
        <p className="page-subtitle">原标题：{item.title}</p>
      )}

      <div className="card-meta" style={{ marginBottom: 18 }}>
        <span>{item.source.name}</span>
        {item.source.tier === "primary" && <span className="tag tag-primary">一手来源</span>}
        {item.contentType && (
          <span className="tag">
            {CONTENT_TYPE_LABELS[item.contentType] ?? item.contentType}
          </span>
        )}
        {typeof item.qualityScore === "number" && (
          <span className="tag">质量 {Math.round(item.qualityScore)}</span>
        )}
      </div>

      <div className="detail-body">
        {item.summary ? (
          <>
            <h2 style={{ fontSize: 15, margin: "0 0 8px" }}>AI 摘要</h2>
            <p style={{ margin: "0 0 18px" }}>{item.summary}</p>
            <div className="notice">
              以上摘要由 AI 生成，可能存在误差。事实请以原文为准。
            </div>
          </>
        ) : (
          <div className="notice">该条目尚未完成 AI 结构化，以下为正文节选。</div>
        )}

        {item.excerpt && (
          <>
            <h2 style={{ fontSize: 15, margin: "18px 0 8px" }}>正文节选</h2>
            <p style={{ margin: 0, color: "#43433f" }}>{item.excerpt}</p>
          </>
        )}

        <hr style={{ border: 0, borderTop: "1px solid var(--border)", margin: "22px 0" }} />

        <dl style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>
          <div>发布时间：{formatDateTime(item.publishedAt)}</div>
          <div>抓取时间：{formatDateTime(item.observedAt)}</div>
          <div>来源机构：{item.source.organization ?? item.source.name}</div>
        </dl>

        {/* Evidence always resolves to the publisher, never to our copy
            (AHR-SPEC-000 ADR-009). This is the page's primary action, so it
            reads as one rather than as another neutral outline button. */}
        <a
          className="origin-link"
          href={item.canonicalUrl}
          target="_blank"
          rel="noreferrer noopener"
        >
          阅读原文
          <svg
            className="origin-link-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M7 17 17 7" />
            <path d="M9 7h8v8" />
          </svg>
          {hostOf(item.canonicalUrl) && (
            <span className="origin-link-host">{hostOf(item.canonicalUrl)}</span>
          )}
        </a>
      </div>
    </>
  );
}

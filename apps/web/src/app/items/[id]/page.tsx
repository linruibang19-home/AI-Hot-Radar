import Link from "next/link";
import { notFound } from "next/navigation";
import { CONTENT_TYPE_LABELS } from "@/components/ItemCard";
import { fetchItem } from "@/lib/api";

export const dynamic = "force-dynamic";

function formatDateTime(value?: string): string {
  if (!value) return "未知";
  return `${value.slice(0, 10)} ${value.slice(11, 16)} UTC`;
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
      <p className="page-subtitle">
        <Link href="/items">← 返回全部动态</Link>
      </p>

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

        <p style={{ marginTop: 20 }}>
          {/* Evidence always resolves to the publisher, never to our copy
              (AHR-SPEC-000 ADR-009). */}
          <a className="button" href={item.canonicalUrl} target="_blank" rel="noreferrer noopener">
            阅读原文 ↗
          </a>
        </p>
      </div>
    </>
  );
}

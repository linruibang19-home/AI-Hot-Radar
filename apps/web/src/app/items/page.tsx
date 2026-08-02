import Link from "next/link";

import { ItemCard } from "@/components/ItemCard";
import { fetchItems } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "全部 AI 动态",
  description: "候选池全量 AI 资讯，按发布时间倒序，支持关键词搜索。",
};

export const dynamic = "force-dynamic";

interface SearchParams {
  cursor?: string;
  q?: string;
  contentType?: string;
}

export default async function ItemsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const page = await fetchItems({
    limit: 25,
    cursor: params.cursor,
    q: params.q,
    contentType: params.contentType,
  });

  const nextHref = page.page.nextCursor
    ? `/items?${new URLSearchParams({
        cursor: page.page.nextCursor,
        ...(params.q ? { q: params.q } : {}),
        ...(params.contentType ? { contentType: params.contentType } : {}),
      })}`
    : null;

  return (
    <>
      <h1 className="page-title">全部 AI 动态</h1>
      <p className="page-subtitle">
        候选池全量内容，按发布时间倒序
        {params.q ? ` · 搜索「${params.q}」` : ""}
      </p>

      <form method="get" action="/items" style={{ marginBottom: 18 }}>
        <input
          type="search"
          name="q"
          defaultValue={params.q ?? ""}
          placeholder="搜索标题…"
          style={{
            padding: "8px 12px",
            border: "1px solid var(--border)",
            borderRadius: 8,
            width: 260,
            fontSize: 14,
          }}
        />
        <button type="submit" className="button" style={{ marginLeft: 8 }}>
          搜索
        </button>
      </form>

      {page.data.length === 0 ? (
        <div className="empty">没有匹配的内容。</div>
      ) : (
        page.data.map((item) => <ItemCard key={item.id} item={item} />)
      )}

      {nextHref && (
        <div className="pager">
          <Link className="button" href={nextHref}>
            加载更多
          </Link>
        </div>
      )}
    </>
  );
}

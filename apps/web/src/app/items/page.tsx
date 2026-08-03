import { formatTime } from "@/lib/datetime";
import Link from "next/link";

import { CategoryTabs, SearchBox } from "@/components/CategoryTabs";
import { ItemCard } from "@/components/ItemCard";
import { TimelineDay, TimelineRow } from "@/components/Timeline";
import { fetchCategories, fetchItems, groupByDay } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "全部 AI 动态",
  description: "候选池全量 AI 资讯，按发布时间倒序，支持分类筛选与关键词搜索。",
};

export const dynamic = "force-dynamic";

const OPEN_DAYS = 2;

interface SearchParams {
  cursor?: string;
  q?: string;
  category?: string;
}

export default async function ItemsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const category = params.category ?? "all";

  const [page, categories] = await Promise.all([
    fetchItems({
      limit: 25,
      cursor: params.cursor,
      q: params.q,
      contentType: category === "all" ? undefined : category,
    }),
    fetchCategories(),
  ]);

  const groups = groupByDay(page.data);

  const nextHref = page.page.nextCursor
    ? `/items?${new URLSearchParams({
        cursor: page.page.nextCursor,
        ...(params.q ? { q: params.q } : {}),
        ...(category !== "all" ? { category } : {}),
      })}`
    : null;

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">全部 AI 动态</h1>
        <p className="page-subtitle">
          候选池全量内容，按发布时间倒序 · 中文标题与摘要由模型生成，事实以原文为准
          {params.q ? ` · 搜索「${params.q}」` : ""}
        </p>
      </header>

      <div className="toolbar">
        <CategoryTabs
          tabs={categories}
          active={category}
          basePath="/items"
          params={{ q: params.q }}
        />
        <SearchBox action="/items" defaultValue={params.q} category={category} />
      </div>

      {params.q && (
        <p className="filter-note">
          <Link href={category === "all" ? "/items" : `/items?category=${category}`}>
            清除搜索
          </Link>
        </p>
      )}

      {page.data.length === 0 ? (
        <div className="empty">没有匹配的内容。</div>
      ) : (
        [...groups.entries()].map(([day, items], index) => (
          <TimelineDay
            key={day}
            day={day}
            count={items.length}
            defaultOpen={index < OPEN_DAYS}
          >
            {items.map((item) => (
              <TimelineRow
                key={item.id}
                time={formatTime(item.publishedAt ?? item.observedAt)}
              >
                <ItemCard item={item} />
              </TimelineRow>
            ))}
          </TimelineDay>
        ))
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

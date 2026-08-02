import Link from "next/link";

import { CategoryTabs } from "@/components/CategoryTabs";
import { ItemCard } from "@/components/ItemCard";
import { fetchCategories, fetchItems, groupByDay } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "全部 AI 动态",
  description: "候选池全量 AI 资讯，按发布时间倒序，支持分类筛选与关键词搜索。",
};

export const dynamic = "force-dynamic";

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function formatDay(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return day;
  return `${date.getUTCMonth() + 1}月${date.getUTCDate()}日 · ${WEEKDAYS[date.getUTCDay()]}`;
}

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
      <h1 className="page-title">全部 AI 动态</h1>
      <p className="page-subtitle">
        候选池全量内容，按发布时间倒序 · 中文标题与摘要由模型生成，事实以原文为准
        {params.q ? ` · 搜索「${params.q}」` : ""}
      </p>

      <CategoryTabs
        tabs={categories}
        active={category}
        basePath="/items"
        params={{ q: params.q }}
      />

      <form method="get" action="/items" className="filter-form">
        {/* The category has to survive a search, otherwise submitting the form
            silently drops the active tab. */}
        {category !== "all" && <input type="hidden" name="category" value={category} />}
        <input
          type="search"
          name="q"
          defaultValue={params.q ?? ""}
          placeholder="搜索标题、模型名或版本号…"
          className="filter-input"
          aria-label="搜索内容"
        />
        <button type="submit" className="button">
          搜索
        </button>
        {params.q && (
          <Link className="filter-clear" href={category === "all" ? "/items" : `/items?category=${category}`}>
            清除搜索
          </Link>
        )}
      </form>

      {page.data.length === 0 ? (
        <div className="empty">没有匹配的内容。</div>
      ) : (
        [...groups.entries()].map(([day, items]) => (
          <section key={day}>
            <h2 className="day-heading">
              {formatDay(day)}
              <span className="day-count">{items.length} 条</span>
            </h2>
            {items.map((item) => (
              <ItemCard key={item.id} item={item} />
            ))}
          </section>
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

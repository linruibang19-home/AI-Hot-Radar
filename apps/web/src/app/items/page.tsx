import Link from "next/link";

import { CategoryTabs, SearchBox } from "@/components/CategoryTabs";
import { ItemsFeed } from "@/components/ItemsFeed";
import { fetchCategories, fetchItemDays, fetchItems } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "全部 AI 动态",
  description: "候选池全量 AI 资讯，按发布时间倒序，支持分类筛选与关键词搜索。",
};

export const dynamic = "force-dynamic";

interface SearchParams {
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

  const contentType = category === "all" ? undefined : category;

  const [days, categories] = await Promise.all([
    fetchItemDays({ q: params.q, contentType }),
    fetchCategories(),
  ]);

  // The newest day is server-rendered so the page has content in its HTML for
  // crawlers and for the first paint; the rest arrive when a reader opens them.
  const firstDay = days[0]?.day;
  const firstPage = firstDay
    ? await fetchItems({ limit: 50, day: firstDay, q: params.q, contentType })
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

      <ItemsFeed
        // Keyed by the active filters so switching category or search resets
        // the per-day cache; without it the client would keep showing the
        // previous filter's items under the new headings.
        key={`${category}:${params.q ?? ""}`}
        days={days}
        initialDay={firstDay}
        initialItems={firstPage?.data ?? []}
        initialComplete={firstPage ? !firstPage.page.hasMore : true}
        query={params.q}
        category={category}
      />
    </>
  );
}

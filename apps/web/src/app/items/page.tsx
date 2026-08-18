import Link from "next/link";

import { CategoryTabs, SearchBox } from "@/components/CategoryTabs";
import { ItemsFeed } from "@/components/ItemsFeed";
import { fetchCategories, fetchItemDays, fetchItems } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "全部 AI 动态",
  description: "已完成中文结构化的 AI 资讯，按发布时间倒序，支持分类筛选与关键词搜索。",
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
        {/* 副标题原本解释了入库口径、排序和免责。标题、下方的分类计数和搜索框
            已经说明了这些，留在这里只是把规格说明搬到了用户眼前。 */}
        {params.q ? <p className="page-subtitle">搜索「{params.q}」</p> : null}
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

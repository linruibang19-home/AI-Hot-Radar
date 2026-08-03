import { dayKey, formatTime, formatWeekday } from "@/lib/datetime";
import { CategoryTabs, SearchBox } from "@/components/CategoryTabs";
import { HotList } from "@/components/HotList";
import { ItemCard } from "@/components/ItemCard";
import { SortToggle } from "@/components/SortToggle";
import { TimelineDay, TimelineRow } from "@/components/Timeline";
import { fetchCategories, fetchHot, fetchSelected, fetchStats } from "@/lib/api";
import type { SelectedItem, SelectionSort } from "@/lib/api";

// SSR on every request so the first screen is always current (AHR-FEAT-101).
export const dynamic = "force-dynamic";

/** How many day sections start expanded. Older days collapse to stay scannable. */
const OPEN_DAYS = 2;

function formatToday(): string {
  // The server's clock is UTC; the heading must read as the visitor's date.
  const key = dayKey(new Date().toISOString()) ?? "";
  const [year, month, day] = key.split("-");
  return `${year}年${Number(month)}月${Number(day)}日星期${formatWeekday(key).slice(2)}`;
}

/**
 * Group entries under a heading appropriate to the active sort.
 *
 * Under "按精选日" the heading is the editorial date the item was picked; under
 * "按发布时间" it is the article's own publication day. Keeping the day heading
 * tied to the sort key avoids a list that looks unsorted because it is grouped
 * by one date and ordered by another.
 */
function groupEntries(
  entries: SelectedItem[],
  sort: SelectionSort,
): Map<string, SelectedItem[]> {
  const groups = new Map<string, SelectedItem[]>();
  for (const entry of entries) {
    const stamp = entry.item.publishedAt ?? entry.item.observedAt;
    const key =
      sort === "latest" ? (dayKey(stamp) ?? "未知日期") : entry.selectedFor;
    const bucket = groups.get(key);
    if (bucket) bucket.push(entry);
    else groups.set(key, [entry]);
  }
  return groups;
}

interface SearchParams {
  category?: string;
  sort?: string;
  q?: string;
}

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const category = params.category ?? "all";
  const sort: SelectionSort =
    params.sort === "latest" || params.sort === "heat" ? params.sort : "curated";

  const [selected, stats, hot, categories] = await Promise.all([
    fetchSelected(7, 60, { contentType: category, sort }),
    fetchStats(),
    fetchHot(8),
    fetchCategories(),
  ]);

  const groups = groupEntries(selected, sort);
  const activeLabel = categories.find((tab) => tab.key === category)?.label;

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">精选</h1>
        <p className="page-subtitle">
          {formatToday()} · AI 自动挑选的高价值内容 · 推荐理由由模型阅读全文后逐条撰写
        </p>
      </header>

      <div className="toolbar">
        <CategoryTabs
          tabs={categories}
          active={category}
          basePath="/"
          params={{ sort: params.sort }}
        />
        <SearchBox action="/items" defaultValue={params.q} category={category} />
      </div>

      <div className="stat-row">
        <div className="stat">
          <div className="stat-value">{stats.items}</div>
          <div className="stat-label">已入库内容</div>
        </div>
        <div className="stat">
          <div className="stat-value">{stats.activeSources}</div>
          <div className="stat-label">活跃信源</div>
        </div>
        <div className="stat">
          <div className="stat-value">{stats.enriched}</div>
          <div className="stat-label">已 AI 结构化</div>
        </div>
        <div className="stat">
          <div className="stat-value">{stats.chunks}</div>
          <div className="stat-label">检索分块</div>
        </div>
      </div>

      <HotList items={hot} />

      <SortToggle
        active={sort}
        basePath="/"
        params={{ category: category === "all" ? undefined : category }}
      />

      {selected.length === 0 ? (
        <div className="empty">
          {category === "all" ? (
            <>
              尚未生成精选。请先运行：
              <br />
              <code>docker compose exec ai-service python -m ahr.cli select</code>
            </>
          ) : (
            <>「{activeLabel ?? category}」分类下暂无精选内容，换一个分类看看。</>
          )}
        </div>
      ) : (
        [...groups.entries()].map(([day, entries], index) => (
          <TimelineDay
            key={day}
            day={day}
            count={entries.length}
            defaultOpen={index < OPEN_DAYS}
          >
            {entries.map((entry) => (
              <TimelineRow
                key={entry.item.id}
                time={formatTime(entry.item.publishedAt ?? entry.item.observedAt)}
              >
                <ItemCard item={entry.item} selectionReason={entry.reason} curated />
              </TimelineRow>
            ))}
          </TimelineDay>
        ))
      )}
    </>
  );
}

import { CategoryTabs } from "@/components/CategoryTabs";
import { HotList } from "@/components/HotList";
import { ItemCard } from "@/components/ItemCard";
import { SortToggle } from "@/components/SortToggle";
import { fetchCategories, fetchHot, fetchSelected, fetchStats } from "@/lib/api";
import type { SelectedItem, SelectionSort } from "@/lib/api";

// SSR on every request so the first screen is always current (AHR-FEAT-101).
export const dynamic = "force-dynamic";

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function formatDay(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return day;
  return `${date.getUTCMonth() + 1}月${date.getUTCDate()}日 · ${WEEKDAYS[date.getUTCDay()]}`;
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
      sort === "latest" ? (stamp ? stamp.slice(0, 10) : "未知日期") : entry.selectedFor;
    const bucket = groups.get(key);
    if (bucket) bucket.push(entry);
    else groups.set(key, [entry]);
  }
  return groups;
}

interface SearchParams {
  category?: string;
  sort?: string;
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
      <h1 className="page-title">精选</h1>
      <p className="page-subtitle">
        AI 自动挑选的高价值内容 · 推荐理由由模型阅读全文后逐条撰写，并标注局限
      </p>

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

      <CategoryTabs
        tabs={categories}
        active={category}
        basePath="/"
        params={{ sort: params.sort }}
      />
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
        [...groups.entries()].map(([day, entries]) => (
          <section key={day}>
            <h2 className="day-heading">
              {formatDay(day)}
              <span className="day-count">{entries.length} 条精选</span>
            </h2>
            {entries.map((entry) => (
              <ItemCard
                key={entry.item.id}
                item={entry.item}
                selectionReason={entry.reason}
                selectionScore={entry.score}
              />
            ))}
          </section>
        ))
      )}
    </>
  );
}

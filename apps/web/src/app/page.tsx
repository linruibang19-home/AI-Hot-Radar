import { ItemCard } from "@/components/ItemCard";
import { fetchSelected, fetchStats } from "@/lib/api";
import type { SelectedItem } from "@/lib/api";

// SSR on every request so the first screen is always current (AHR-FEAT-101).
export const dynamic = "force-dynamic";

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function formatDay(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return day;
  return `${date.getUTCMonth() + 1}月${date.getUTCDate()}日 · ${WEEKDAYS[date.getUTCDay()]}`;
}

function groupBySelectedDate(entries: SelectedItem[]): Map<string, SelectedItem[]> {
  const groups = new Map<string, SelectedItem[]>();
  for (const entry of entries) {
    const bucket = groups.get(entry.selectedFor);
    if (bucket) bucket.push(entry);
    else groups.set(entry.selectedFor, [entry]);
  }
  return groups;
}

export default async function Home() {
  const [selected, stats] = await Promise.all([fetchSelected(7, 60), fetchStats()]);
  const groups = groupBySelectedDate(selected);

  return (
    <>
      <h1 className="page-title">精选</h1>
      <p className="page-subtitle">AI 自动挑选的高价值内容 · 每条都标注入选理由与原始来源</p>

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

      {selected.length === 0 ? (
        <div className="empty">
          尚未生成精选。请先运行：
          <br />
          <code>docker compose exec ai-service python -m ahr.cli select</code>
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

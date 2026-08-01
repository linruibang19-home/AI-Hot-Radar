import { ItemCard } from "@/components/ItemCard";
import { fetchItems, fetchStats, groupByDay } from "@/lib/api";

// SSR on every request so the first screen is always current (AHR-FEAT-101).
export const dynamic = "force-dynamic";

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function formatDay(day: string): string {
  if (day === "未知日期") return day;
  const date = new Date(`${day}T00:00:00Z`);
  return `${date.getUTCMonth() + 1}月${date.getUTCDate()}日 · ${WEEKDAYS[date.getUTCDay()]}`;
}

export default async function Home() {
  const [page, stats] = await Promise.all([fetchItems({ limit: 30 }), fetchStats()]);
  const groups = groupByDay(page.data);

  return (
    <>
      <h1 className="page-title">精选</h1>
      <p className="page-subtitle">AI 自动挑选的高价值内容 · 全部来自可追溯的公开信源</p>

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

      {page.data.length === 0 ? (
        <div className="empty">
          暂无内容。请先运行采集：
          <br />
          <code>docker compose exec ai-service python -m ahr.cli ingest</code>
        </div>
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
    </>
  );
}

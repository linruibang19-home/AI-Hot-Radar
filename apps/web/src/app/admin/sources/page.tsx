import { formatShortDateTime } from "@/lib/datetime";
import type { SourceHealth } from "@/lib/api";
import { fetchSourceHealth } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "信源后台",
  description: "信源运行状态、全文成功率与错误诊断。",
};

export const dynamic = "force-dynamic";

function formatTime(value?: string | null): string {
  if (!value) return "—";
  return formatShortDateTime(value);
}

function summarise(sources: SourceHealth[]) {
  const counts = new Map<string, number>();
  for (const source of sources) {
    counts.set(source.runtimeState, (counts.get(source.runtimeState) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

export default async function AdminSourcesPage() {
  const sources = await fetchSourceHealth();
  const states = summarise(sources);

  return (
    <>
      <h1 className="page-title">信源后台</h1>
      <p className="page-subtitle">
        只读视图 · 排序把失败的信源放在最前 · 启停与重跑需要鉴权，属于 M5
      </p>

      <div className="stat-row">
        {states.map(([state, count]) => (
          <div className="stat" key={state}>
            <div className="stat-value">{count}</div>
            <div className="stat-label">{state}</div>
          </div>
        ))}
      </div>

      {sources.length === 0 ? (
        <div className="empty">无法读取信源状态。</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>信源</th>
              <th>类型</th>
              <th>状态</th>
              <th>内容数</th>
              <th>全文率</th>
              <th>最近成功</th>
              <th>最近错误</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.id}>
                <td>
                  {source.name}
                  <div style={{ color: "var(--muted)", fontSize: 11 }}>
                    {source.organization} · {source.priority}
                  </div>
                </td>
                <td style={{ color: "var(--muted)" }}>{source.profile}</td>
                <td>
                  <span className={`state state-${source.runtimeState}`}>
                    {source.runtimeState}
                  </span>
                </td>
                <td>{source.items}</td>
                <td>
                  {source.fulltextSuccessRate === null ||
                  source.fulltextSuccessRate === undefined
                    ? "—"
                    : `${source.fulltextSuccessRate}%`}
                </td>
                <td style={{ color: "var(--muted)" }}>{formatTime(source.lastSuccessAt)}</td>
                <td style={{ color: source.lastErrorCode ? "#a33" : "var(--muted)" }}>
                  {source.lastErrorCode ?? "—"}
                  {source.consecutiveFailures > 0 && ` (${source.consecutiveFailures})`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

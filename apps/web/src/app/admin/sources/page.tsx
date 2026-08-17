import { formatShortDateTime } from "@/lib/datetime";
import type { SourceHealth } from "@/lib/api";
import { fetchSourceHealth, fetchSourceHealthSummary } from "@/lib/api";
import { SourceRefreshButton } from "@/components/SourceRefreshButton";

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
  const [sources, summary] = await Promise.all([
    fetchSourceHealth(),
    fetchSourceHealthSummary(),
  ]);
  const states = summarise(sources);
  const renderedAt = new Date().toISOString();
  const publicOrigin = process.env.PUBLIC_BASE_URL ?? "http://localhost:3000";
  const environment = publicOrigin.includes("localhost") ? "本地开发" : "生产";
  const registered = summary?.registered ?? sources.length;
  const enabled = summary?.enabled ?? sources.length;
  const disabled = summary?.disabled ?? Math.max(registered - enabled, 0);

  return (
    <>
      <header className="source-page-head">
        <div>
          <h1 className="page-title">信源后台</h1>
          <p className="page-subtitle">
            排序把失败的信源放在最前 · 本页用<strong>只读凭据</strong>渲染，
            启停与重跑走 <code>/api/v1/admin</code>，需要 OPERATOR 凭据、二次确认，并逐条留痕
          </p>
        </div>
        <SourceRefreshButton />
      </header>

      <p className="source-freshness">
        当前环境：<strong>{environment}</strong>（{publicOrigin}）。调度器持续把采集结果写入该环境自己的
        PostgreSQL；本页不会主动采集、同步另一环境或自动轮询。数据库状态截至{" "}
        <time dateTime={summary?.dataUpdatedAt ?? undefined}>
          {formatTime(summary?.dataUpdatedAt)}
        </time>
        ，页面读取于 <time dateTime={renderedAt}>{formatTime(renderedAt)}</time>。
      </p>

      <div className="stat-row">
        {states.map(([state, count]) => (
          <div className="stat" key={state}>
            <div className="stat-value">{count}</div>
            <div className="stat-label">{state}</div>
          </div>
        ))}
      </div>

      <p className="filter-note">
        当前数据库注册 {registered} 个信源，其中 {enabled} 个有效启用、{disabled} 个关闭；
        下表显示 {sources.length} 个有效启用信源。配置版本：{summary?.configVersion ?? "未知"}。
      </p>

      {sources.length === 0 ? (
        <div className="empty">无法读取信源状态。</div>
      ) : (
        <div className="table-scroll">
        <table className="table table-sources">
          <colgroup>
            <col />
            <col className="col-profile" />
            <col className="col-state" />
            <col className="col-num" />
            <col className="col-num" />
            <col className="col-time" />
            <col className="col-error" />
          </colgroup>
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
                {/* `title` because the longest codes (RESPONSE_TOO_LARGE,
                    ACCESS_RESTRICTED) can still outrun the column even at the
                    table's minimum width, and a half-read error code is worse
                    than none — it looks like a different error. */}
                <td
                  style={{ color: source.lastErrorCode ? "#a33" : "var(--muted)" }}
                  title={source.lastErrorCode ?? undefined}
                >
                  {source.lastErrorCode ?? "—"}
                  {source.consecutiveFailures > 0 && ` (${source.consecutiveFailures})`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </>
  );
}

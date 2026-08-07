import { formatShortDateTime } from "@/lib/datetime";
import type { SourceHealth } from "@/lib/api";
import { fetchSourceHealth } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "信源后台",
  description: "信源运行状态、全文成功率与错误诊断。",
};

export const dynamic = "force-dynamic";

/** Rows in `config/sources.yaml`, the registry this page is a view onto. */
const REGISTRY_TOTAL = 140;

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
        排序把失败的信源放在最前 · 本页用<strong>只读凭据</strong>渲染，
        启停与重跑走 <code>/api/v1/admin</code>，需要 OPERATOR 凭据、二次确认，并逐条留痕
      </p>

      <div className="stat-row">
        {states.map(([state, count]) => (
          <div className="stat" key={state}>
            <div className="stat-value">{count}</div>
            <div className="stat-label">{state}</div>
          </div>
        ))}
      </div>

      {/* The registry holds 140 sources; this page lists the enabled ones. A
          reader seeing 124 has no way to tell whether the rest are missing or
          switched off on purpose, and "switched off on purpose" is the answer:
          Wave C needs a browser renderer, and `verification: restricted`
          sources default to disabled by policy. */}
      <p className="filter-note">
        共 {sources.length} 个已启用信源。注册表里另有 {REGISTRY_TOTAL - sources.length}{" "}
        个默认关闭（需浏览器渲染的 SPA、以及按来源政策默认停用的受限源），不在此列。
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

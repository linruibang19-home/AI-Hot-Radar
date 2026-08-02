import Link from "next/link";

import {
  REPORT_PERIODS,
  fetchReports,
  formatPeriodKey,
  groupReports,
  normalisePeriod,
} from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI 日报 / 周报 / 月报",
  description: "由精选内容生成的 AI 行业日报、周报与月报，每个条目都可追溯到原文。",
};

export const dynamic = "force-dynamic";

const CLI_HINT: Record<string, string> = {
  daily: "python -m ahr.cli report --period daily",
  weekly: "python -m ahr.cli report --period weekly",
  monthly: "python -m ahr.cli report --period monthly",
};

export default async function ReportsPage({
  searchParams,
}: {
  searchParams: Promise<{ period?: string }>;
}) {
  const params = await searchParams;
  const period = normalisePeriod(params.period);
  const reports = await fetchReports(60, period);
  const archive = groupReports(period, reports);
  const active = REPORT_PERIODS.find((entry) => entry.key === period);

  return (
    <>
      <h1 className="page-title">AI 报告</h1>
      <p className="page-subtitle">
        {active?.blurb} · 总述由模型基于当期精选生成，所有条目均链接回原始来源
      </p>

      <nav className="tabs" aria-label="报告周期">
        {REPORT_PERIODS.map((entry) => {
          const current = entry.key === period;
          return (
            <Link
              key={entry.key}
              href={entry.key === "daily" ? "/reports" : `/reports?period=${entry.key}`}
              className={current ? "tab tab-active" : "tab"}
              aria-current={current ? "page" : undefined}
            >
              {entry.label}
            </Link>
          );
        })}
      </nav>

      {reports.length === 0 ? (
        <div className="empty">
          尚无{active?.label}。请先生成：
          <br />
          <code>docker compose exec ai-service {CLI_HINT[period]}</code>
        </div>
      ) : (
        [...archive.entries()].map(([label, entries]) => (
          <section key={label}>
            <h2 className="day-heading">
              {label}
              <span className="day-count">{entries.length} 期</span>
            </h2>
            {entries.map((report) => (
              <article className="card" key={report.date}>
                <div className="card-meta">
                  <span>{formatPeriodKey(period, report.date)}</span>
                  <span>·</span>
                  <span>{report.itemCount} 条精选</span>
                  {report.modelName && <span className="tag">{report.modelName}</span>}
                </div>
                <h3 className="card-title">
                  <Link href={`/reports/${period}/${report.date}`}>{report.title}</Link>
                </h3>
                {report.summary && (
                  <p className="card-summary">{report.summary.slice(0, 220)}…</p>
                )}
              </article>
            ))}
          </section>
        ))
      )}
    </>
  );
}

import Link from "next/link";

import { fetchReports } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI 日报",
  description: "每日精选生成的 AI 行业日报，条目可追溯到原文。",
};

export const dynamic = "force-dynamic";

export default async function ReportsPage() {
  const reports = await fetchReports(30);

  return (
    <>
      <h1 className="page-title">AI 日报</h1>
      <p className="page-subtitle">
        每期日报都由当日精选内容生成，所有条目可追溯到原始来源
      </p>

      {reports.length === 0 ? (
        <div className="empty">
          尚无日报。请先生成：
          <br />
          <code>docker compose exec ai-service python -m ahr.cli report</code>
        </div>
      ) : (
        reports.map((report) => (
          <article className="card" key={report.date}>
            <div className="card-meta">
              <span>{report.date}</span>
              <span>·</span>
              <span>{report.itemCount} 条精选</span>
              {report.modelName && <span className="tag">{report.modelName}</span>}
            </div>
            <h3 className="card-title">
              <Link href={`/reports/daily/${report.date}`}>{report.title}</Link>
            </h3>
            {report.summary && (
              <p className="card-summary">{report.summary.slice(0, 220)}…</p>
            )}
          </article>
        ))
      )}
    </>
  );
}

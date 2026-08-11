import { ReportWorkspace } from "@/components/ReportWorkspace";
import { REPORT_PERIODS, fetchReport, fetchReports, normalisePeriod } from "@/lib/api";

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
  const active = REPORT_PERIODS.find((entry) => entry.key === period);

  if (reports.length === 0) {
    return (
      <section className="report-empty" aria-labelledby="report-empty-title">
        <p>{active?.blurb}</p>
        <h1 id="report-empty-title">尚无{active?.label}</h1>
        <p>报告生成后会在这里形成可按周期浏览的出版式档案。</p>
        <code>docker compose exec ai-service {CLI_HINT[period]}</code>
      </section>
    );
  }

  const report = await fetchReport(period, reports[0].date);
  if (!report) {
    return (
      <section className="report-empty" aria-labelledby="report-empty-title">
        <h1 id="report-empty-title">报告索引与正文暂时不同步</h1>
        <p>列表记录存在，但正文读取失败。请稍后重试或检查 core-api 日志。</p>
      </section>
    );
  }

  return <ReportWorkspace period={period} reports={reports} report={report} />;
}

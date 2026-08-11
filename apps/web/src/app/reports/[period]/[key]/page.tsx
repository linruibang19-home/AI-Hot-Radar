import { notFound } from "next/navigation";

import { ReportWorkspace } from "@/components/ReportWorkspace";
import { fetchReport, fetchReports, normalisePeriod } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ReportPage({
  params,
}: {
  params: Promise<{ period: string; key: string }>;
}) {
  const raw = await params;
  const period = normalisePeriod(raw.period);

  // Do not silently turn an invalid URL into a daily report.
  if (raw.period !== period) {
    notFound();
  }

  const [reports, report] = await Promise.all([
    fetchReports(60, period),
    fetchReport(period, raw.key),
  ]);

  if (!report) {
    notFound();
  }

  return <ReportWorkspace period={period} reports={reports} report={report} />;
}

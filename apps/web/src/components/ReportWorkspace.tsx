import Link from "next/link";

import {
  REPORT_PERIODS,
  groupReports,
  reportWindow,
} from "@/lib/api";

import type {
  ReportDetail,
  ReportEntry,
  ReportPeriod,
  ReportSummary,
} from "@/lib/api";

const PERIOD_EDITORIAL: Record<
  ReportPeriod,
  { eyebrow: string; heading: string; overview: string; footer: string }
> = {
  daily: {
    eyebrow: "DAILY INTELLIGENCE",
    heading: "日报",
    overview: "今日看点",
    footer: "逐条速览当天值得追踪的 AI 变化",
  },
  weekly: {
    eyebrow: "WEEKLY SIGNALS",
    heading: "周报",
    overview: "本周主线",
    footer: "把一周内反复出现的事件收敛为趋势",
  },
  monthly: {
    eyebrow: "MONTHLY REVIEW",
    heading: "月报",
    overview: "本月格局",
    footer: "回看能力边界、竞争方向与行业结构变化",
  },
};

function reportHref(period: ReportPeriod, key: string): string {
  return `/reports/${period}/${encodeURIComponent(key)}`;
}

function periodHref(period: ReportPeriod): string {
  return period === "daily" ? "/reports" : `/reports?period=${period}`;
}

function leadText(report: ReportSummary): string {
  const source = report.summary?.trim() || report.title;
  const firstSentence = source.split(/[。！？]/, 1)[0]?.trim() || source;
  return firstSentence.length > 34 ? `${firstSentence.slice(0, 34)}…` : firstSentence;
}

function compactDate(period: ReportPeriod, key: string): string {
  if (period === "daily") return `${Number(key.slice(8, 10))} 日`;
  if (period === "weekly") return `第${Number(key.slice(-2))}周`;
  return `${Number(key.slice(-2))} 月`;
}

function tierClass(tier: string): string {
  if (tier === "primary") return "tier-primary";
  if (tier === "secondary" || tier === "authoritative_secondary") return "tier-secondary";
  if (tier === "expert") return "tier-expert";
  return "tier-community";
}

function tierLabel(tier: string): string {
  if (tier === "primary") return "一手来源";
  if (tier === "secondary" || tier === "authoritative_secondary") return "权威二手";
  if (tier === "expert") return "专家来源";
  return "社区来源";
}

function ReportArchive({
  period,
  reports,
  currentKey,
}: {
  period: ReportPeriod;
  reports: ReportSummary[];
  currentKey: string;
}) {
  const archive = groupReports(period, reports);

  return (
    <aside className="report-archive" aria-label="报告档案">
      <nav className="report-periods" aria-label="报告周期">
        {REPORT_PERIODS.map((entry) => {
          const current = entry.key === period;
          return (
            <Link
              key={entry.key}
              href={periodHref(entry.key)}
              className={current ? "report-period is-active" : "report-period"}
              aria-current={current ? "page" : undefined}
            >
              {entry.label}
            </Link>
          );
        })}
      </nav>

      <details className="report-archive-disclosure" open>
        <summary>浏览{PERIOD_EDITORIAL[period].heading}档案</summary>
        <div className="report-archive-groups">
          {[...archive.entries()].map(([label, entries]) => (
            <section className="report-archive-group" key={label}>
              <h2>
                {label}
                <span>{entries.length}</span>
              </h2>
              <ol>
                {entries.map((entry) => {
                  const current = entry.date === currentKey;
                  return (
                    <li key={entry.date}>
                      <Link
                        href={reportHref(period, entry.date)}
                        className={current ? "report-archive-link is-active" : "report-archive-link"}
                        aria-current={current ? "page" : undefined}
                      >
                        <span className="report-archive-date">{compactDate(period, entry.date)}</span>
                        <span className="report-archive-title">{leadText(entry)}</span>
                      </Link>
                    </li>
                  );
                })}
              </ol>
            </section>
          ))}
        </div>
      </details>
    </aside>
  );
}

function ReportOverview({ report, period }: { report: ReportDetail; period: ReportPeriod }) {
  return (
    <section className="report-overview" aria-labelledby="report-overview-title">
      <div className="report-overview-head">
        <h2 id="report-overview-title">{PERIOD_EDITORIAL[period].overview}</h2>
        <span>
          {report.stats.sections} 个章节 · {report.stats.items} 条情报
        </span>
      </div>
      <ol>
        {report.sections.map((section, index) => (
          <li key={section.key}>
            <span className="report-index">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{section.label}</strong>
              <span>{section.items[0]?.title}</span>
            </div>
            <em>{section.count}</em>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ReportStory({ entry }: { entry: ReportEntry }) {
  return (
    <article className="report-story">
      <h3>
        <a href={entry.canonicalUrl} target="_blank" rel="noreferrer noopener">
          {entry.title}
        </a>
      </h3>
      <div className="report-story-meta">
        <span className={`tier-badge ${tierClass(entry.sourceTier)}`}>
          {tierLabel(entry.sourceTier)}
        </span>
        <span>{entry.sourceName}</span>
        {entry.organization && entry.organization !== entry.sourceName && (
          <span>· {entry.organization}</span>
        )}
        {entry.independentSources > 1 && (
          <span className="corroboration-badge">{entry.independentSources} 家信源</span>
        )}
      </div>
      {entry.summary && <p>{entry.summary}</p>}
      <div className="report-story-actions">
        {entry.storySlug && <Link href={`/stories/${entry.storySlug}`}>查看事件脉络</Link>}
        <a href={entry.canonicalUrl} target="_blank" rel="noreferrer noopener">
          阅读原文 ↗
        </a>
      </div>
    </article>
  );
}

function ReportNavigation({ report, period }: { report: ReportDetail; period: ReportPeriod }) {
  const previous = report.navigation.previousKey;
  const next = report.navigation.nextKey;
  return (
    <nav className="report-navigation" aria-label="报告前后期">
      {previous ? (
        <Link href={reportHref(period, previous)}>← 上一期</Link>
      ) : (
        <span>← 上一期</span>
      )}
      <Link href={periodHref(period)}>查看全部{PERIOD_EDITORIAL[period].heading}</Link>
      {next ? <Link href={reportHref(period, next)}>下一期 →</Link> : <span>下一期 →</span>}
    </nav>
  );
}

function ReportPaper({ report, period }: { report: ReportDetail; period: ReportPeriod }) {
  const copy = PERIOD_EDITORIAL[period];
  return (
    <article className="report-paper">
      <header className="report-masthead">
        <p className="report-volume">
          VOL. {report.date.toUpperCase()} · {report.stats.items} STORIES · {copy.eyebrow}
        </p>
        <h1>AI HOT RADAR {copy.heading}</h1>
        <p className="report-dateline">
          {reportWindow(period, report.date)} · {report.status} · 约 {report.stats.readingMinutes} 分钟
        </p>
        <div className="report-rule" aria-hidden="true" />
      </header>

      <section className="report-lead" aria-labelledby="report-lead-title">
        <span>{copy.overview}</span>
        <h2 id="report-lead-title">{leadText(report)}</h2>
        <p>{report.summary}</p>
      </section>

      <ReportOverview report={report} period={period} />

      <div className="report-sections">
        {report.sections.map((section, index) => (
          <section className="report-section" key={section.key}>
            <header>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <h2>{section.label}</h2>
              <small>{section.key.replaceAll("_", " ").toUpperCase()}</small>
              <em>{section.count} 篇</em>
            </header>
            <div className="report-section-items">
              {section.items.map((entry) => (
                <ReportStory key={entry.id} entry={entry} />
              ))}
            </div>
          </section>
        ))}
      </div>

      <section className="report-stats" aria-label="报告数据概览">
        <div>
          <strong>{report.stats.stories}</strong>
          <span>独立事件</span>
        </div>
        <div>
          <strong>{report.stats.primarySources}</strong>
          <span>一手报道</span>
        </div>
        <div>
          <strong>{report.stats.sources}</strong>
          <span>发布来源</span>
        </div>
        <div>
          <strong>≈{report.stats.readingMinutes} min</strong>
          <span>读完本期</span>
        </div>
      </section>

      <div className="report-next-period">
        <div>
          <strong>{copy.footer}</strong>
          <span>所有事实条目均可回到原始发布方核验</span>
        </div>
        {period !== "monthly" && (
          <Link href={periodHref(period === "daily" ? "weekly" : "monthly")}>
            阅读{period === "daily" ? "周报" : "月报"} →
          </Link>
        )}
      </div>

      <ReportNavigation report={report} period={period} />

      <footer className="report-disclosure">
        <strong>{report.status === "PUBLISHED" ? "已发布" : "DRAFT 预览"}</strong>
        <span>
          总述由 {report.modelName ?? "确定性模板"} 生成；条目来自已保存的精选与 Story，事实以原文为准。
        </span>
        <span>
          生成于 {new Date(report.generatedAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}
          {report.promptVersion ? ` · ${report.promptVersion}` : ""}
        </span>
      </footer>
    </article>
  );
}

export function ReportWorkspace({
  period,
  reports,
  report,
}: {
  period: ReportPeriod;
  reports: ReportSummary[];
  report: ReportDetail;
}) {
  return (
    <div className="report-page">
      <ReportArchive period={period} reports={reports} currentKey={report.date} />
      <ReportPaper period={period} report={report} />
    </div>
  );
}

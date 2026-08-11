import summary from "@/data/eval-summary.json";

import type { Metadata } from "next";

/**
 * The evaluation record, on the site rather than only in the repository.
 *
 * Every round of retrieval evaluation, with per-question data, existed since M4
 * and lived entirely in `docs/status/`. From the outside this looked like a
 * RAG pipeline someone assembled and declared working — which is exactly the
 * thing the evaluation was run to avoid claiming.
 *
 * Two things are deliberately kept and neither is flattering: the round that
 * produced a **worse** result than the baseline (B2's interleaved union), and
 * the round whose conclusion was **change nothing** (B8). A results page that
 * only shows the wins is a marketing page.
 *
 * Regenerate the data with `python scripts/build_eval_summary.py`.
 */

export const metadata: Metadata = {
  title: "RAG 质量",
  description:
    "90 题黄金集上的逐轮检索评测：每轮改了什么、判据是什么、结果是什么，含负结果。",
};

const VERDICTS: Record<string, { label: string; className: string }> = {
  baseline: { label: "基线", className: "verdict-baseline" },
  pass: { label: "达标采纳", className: "verdict-pass" },
  mixed: { label: "有得有失", className: "verdict-mixed" },
  "no-change": { label: "结论：不改", className: "verdict-none" },
};

const CATEGORIES: Record<string, string> = {
  recent_updates: "最新动态",
  timeline: "时间线",
  comparison: "对比",
  fact_check: "事实核查",
  explainer: "原理解释",
  abstention: "不可答",
};

function metric(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : value.toFixed(4);
}

function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

/**
 * The narrative in `eval-summary.json` marks its key phrases with `**…**`, and
 * this page was printing them as literal asterisks — on the one page whose
 * entire claim is being precise about what was measured. Bold is the only
 * markup used, so this stays a split rather than a markdown dependency.
 */
function emphasise(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    /^\*\*[^*]+\*\*$/.test(part) ? (
      <strong key={index}>{part.slice(2, -2)}</strong>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}

/** Change against the previous round, which is the number a reader is after. */
function delta(current?: number | null, previous?: number | null) {
  if (current == null || previous == null) return null;
  const diff = current - previous;
  if (Math.abs(diff) < 0.00005) return <span className="eval-flat">±0</span>;
  return (
    <span className={diff > 0 ? "eval-up" : "eval-down"}>
      {diff > 0 ? "+" : ""}
      {(diff * 100).toFixed(2)}pt
    </span>
  );
}

export default function EvalPage() {
  const { rounds, extra, goldenQuestions, ragas, release } = summary;
  const last = rounds[rounds.length - 1];
  const first = rounds[0];
  const releasePassed =
    release.retrieval["recall@20"] >= 0.85 &&
    release.generation.citation_coverage >= 0.95 &&
    release.generation.support_supported >= 0.9 &&
    release.generation.presupposition_asserted_rate === 0 &&
    release.generation.over_refusal_rate === 0 &&
    release.specialist.passed;

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">RAG 质量</h1>
        <p className="page-subtitle">
          发布门禁、引用可靠性与剩余风险；下方保留 {goldenQuestions} 题黄金集的完整实验记录
        </p>
      </header>

      <section className="quality-hero" aria-labelledby="release-gate-title">
        <div className="quality-hero-head">
          <div>
            <div className="eyebrow">CURRENT RELEASE GATE</div>
            <h2 id="release-gate-title">当前 RAG {releasePassed ? "达到发布门槛" : "未达到发布门槛"}</h2>
          </div>
          <span className={`state ${releasePassed ? "verdict-pass" : "verdict-mixed"}`}>
            {releasePassed ? "可发布" : "需阻断"}
          </span>
        </div>
        <p>
          这不是主观评分：主检索、90 题生成与中文厂商噪声专项分别绑定到可追溯 run。
          自动引用精度受稀疏标注影响，只作诊断；发布正确性采用段落支持门与人工 P0 审计。
        </p>
        <div className="quality-run-ids">
          <code>{release.retrievalRunId}</code>
          <code>{release.generationRunId}</code>
          <code>{release.specialistRunId}</code>
        </div>
      </section>

      <div className="stat-row">
        <div className="stat">
          <div className="stat-value">{percent(release.retrieval["recall@20"])}</div>
          <div className="stat-label">主集 Recall@20 · 门槛 85%</div>
        </div>
        <div className="stat">
          <div className="stat-value">{percent(release.generation.citation_coverage)}</div>
          <div className="stat-label">事实句引用完整性 · 门槛 95%</div>
        </div>
        <div className="stat">
          <div className="stat-value">{percent(release.generation.support_supported)}</div>
          <div className="stat-label">段落支持达标率 · 门槛 90%</div>
        </div>
        <div className="stat">
          <div className="stat-value">0 / {release.generation.answerable}</div>
          <div className="stat-label">可答题误拒</div>
        </div>
        <div className="stat">
          <div className="stat-value">0 / {release.generation.unanswerable}</div>
          <div className="stat-label">诱导题错误断言</div>
        </div>
      </div>

      <div className="quality-grid">
        <article className="quality-card">
          <span className="quality-card-index">01</span>
          <div>
            <h3>检索覆盖已达标</h3>
            <p>
              主集 Recall@20 {percent(release.retrieval["recall@20"])}；15 题中文厂商专项在加入
              真实近邻噪声后仍为 {percent(release.specialist.noiseRecall20)}，没有用第二次查询冒充 A/B。
            </p>
          </div>
        </article>
        <article className="quality-card">
          <span className="quality-card-index">02</span>
          <div>
            <h3>回答出口有硬门</h3>
            <p>
              模型引用不能直接下发；服务端绑定原文、移除弱支持句并处理假前提。
              90 题中可答题误拒与诱导题错误断言都为 0。
            </p>
          </div>
        </article>
        <article className="quality-card quality-card-risk">
          <span className="quality-card-index">03</span>
          <div>
            <h3>上线后仍要持续观察</h3>
            <p>
              噪声结论目前只有 15 题专项样本；每次切换生成模型后必须重跑生成回归。
              自动 citation precision 不能替代人工高风险数字审计。
            </p>
          </div>
        </article>
      </div>

      <div className="notice">
        <strong>下面是算法演进记录，不是当前发布快照。</strong>
        <br />
        从 <strong>{first.id} 纯稠密</strong>（MRR {metric(first.metrics.mrr)}）到{" "}
        <strong>{last.id}</strong>（MRR {metric(last.metrics.mrr)}），提升{" "}
        {(((last.metrics.mrr ?? 0) - (first.metrics.mrr ?? 0)) * 100).toFixed(1)} 个点。
        这里保留了三轮「不好看」的结果：<strong>B2 的并集比基线还差</strong>、
        <strong>B8 扫完 42 组权重后的结论是不改</strong>，以及{" "}
        <strong>B13 修好中文分词后端到端 ±0.0000</strong>。
        只展示赢的那几轮，这页就不是评测记录而是宣传页。
        下面「生成侧与延迟」里还有一条：GEN 写下的<strong>假设被 GEN-FIX 证伪</strong>，
        两轮都留着。
      </div>

      {/* The trend first: one table, one row per round, deltas against the row
          above. Reading down it is the whole argument. */}
      <section className="eval-section">
        {/* Derived, not written. The heading said 十轮 above a nine-row table
            because B5 and B6 changed what the model reads without changing the
            ranking, so they have no retrieval JSON — and a hard-coded count on
            a page about being precise with numbers is the worst place for one
            to drift. */}
        <h2 className="section-title">{rounds.length} 轮检索走势</h2>
        <div className="table-scroll">
          <table className="table eval-table">
            <thead>
              <tr>
                <th>轮次</th>
                <th>改动</th>
                <th>Recall@10</th>
                <th>Recall@20</th>
                <th>MRR</th>
                <th>nDCG@10</th>
                <th>结论</th>
              </tr>
            </thead>
            <tbody>
              {rounds.map((round, index) => {
                const prior = index > 0 ? rounds[index - 1].metrics : null;
                const verdict = VERDICTS[round.verdict] ?? VERDICTS.mixed;
                return (
                  <tr key={round.id}>
                    <td>
                      <a href={`#${round.id}`}>
                        <strong>{round.id}</strong>
                      </a>
                      <div className="eval-meta">{round.title}</div>
                    </td>
                    <td className="eval-changed">{emphasise(round.changed)}</td>
                    <td className="eval-num">
                      {metric(round.metrics.recall10)}
                      <div className="eval-delta">
                        {delta(round.metrics.recall10, prior?.recall10)}
                      </div>
                    </td>
                    <td className="eval-num">
                      {metric(round.metrics.recall20)}
                      <div className="eval-delta">
                        {delta(round.metrics.recall20, prior?.recall20)}
                      </div>
                    </td>
                    <td className="eval-num">
                      {metric(round.metrics.mrr)}
                      <div className="eval-delta">{delta(round.metrics.mrr, prior?.mrr)}</div>
                    </td>
                    <td className="eval-num">
                      {metric(round.metrics.ndcg10)}
                      <div className="eval-delta">{delta(round.metrics.ndcg10, prior?.ndcg10)}</div>
                    </td>
                    <td>
                      <span className={`state ${verdict.className}`}>{verdict.label}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="eval-note">
          B4 与 B7 之后的绝对值不完全可比：B4 当时排除了 2 道标注不可用的题，
          零分块修复后 90 题全部参与。B7 之后是同语料同题集，可以直接比。
        </p>
      </section>

      {/* Then each round in full: what it changed, what it had to beat, and
          what it actually found. The criterion matters most — several were
          registered before the run. */}
      <section className="eval-section">
        <h2 className="section-title">逐轮记录</h2>
        {rounds.map((round) => {
          const verdict = VERDICTS[round.verdict] ?? VERDICTS.mixed;
          return (
            <article className="eval-round" id={round.id} key={round.id}>
              <div className="eval-round-head">
                <h3 className="eval-round-title">
                  {round.id} · {round.title}
                </h3>
                <span className={`state ${verdict.className}`}>{verdict.label}</span>
              </div>
              <div className="eval-run-id">{round.runId}</div>

              <dl className="eval-facts">
                <dt>改了什么</dt>
                <dd>{emphasise(round.changed)}</dd>
                <dt>判据</dt>
                <dd>{emphasise(round.criterion)}</dd>
                <dt>结果</dt>
                <dd>{emphasise(round.finding)}</dd>
              </dl>

              {round.alt && (
                <p className="eval-note">
                  同轮对照 <strong>{round.alt.label}</strong>： Recall@10{" "}
                  {metric(round.alt.metrics.recall10)} · MRR {metric(round.alt.metrics.mrr)} ·
                  nDCG@10 {metric(round.alt.metrics.ndcg10)}
                </p>
              )}

              {Object.keys(round.byCategory).length > 0 && (
                <div className="eval-categories">
                  {Object.entries(round.byCategory).map(([name, row]) => (
                    <div className="eval-category" key={name}>
                      <div className="eval-category-name">{CATEGORIES[name] ?? name}</div>
                      <div className="eval-category-value">MRR {metric(row.mrr)}</div>
                      <div className="eval-category-sub">R@10 {metric(row.recall10)}</div>
                    </div>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </section>

      {/* The same quantities under the names the field uses.
          "We measure groundedness" and "we measure faithfulness" turn out to be
          the same sentence, which is only obvious once someone writes it down.
          The rows with no counterpart in either direction are kept as such. */}
      <section className="eval-section">
        <h2 className="section-title">与 RAGAS 术语的对应</h2>
        <div className="table-scroll">
          <table className="table eval-table">
            <thead>
              <tr>
                <th>RAGAS</th>
                <th>在问什么</th>
                <th>本项目的对应指标</th>
                <th>当前值</th>
              </tr>
            </thead>
            <tbody>
              {ragas.map((row) => (
                <tr key={row.ragas}>
                  <td>
                    <strong>{row.ragas}</strong>
                  </td>
                  <td className="eval-changed">{emphasise(row.asks)}</td>
                  <td className="eval-changed">
                    {emphasise(row.ours)}
                    <div className="eval-meta">{emphasise(row.note)}</div>
                  </td>
                  <td className="eval-num">{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="eval-note">
          三项没有 RAGAS 对应：<strong>story_coverage</strong>（RAGAS 假设文档彼此独立，
          而四家媒体报道同一次披露是<strong>一条</strong>证据不是四条）、
          <strong>citation_coverage</strong>（句级引用覆盖率是本项目的核心主张）、
          以及误拒率。Noise Sensitivity 目前采用 15 题中文厂商专项集与 8 个真实近邻噪声
          做同候选快照 A/B；它已经覆盖最容易串线的场景，但仍只是专项小样本，
          不能冒充完整 90 题噪声回归。
        </p>
      </section>

      {/* Generation and latency are not retrieval metrics and must not be read
          as a continuation of the table above. */}
      <section className="eval-section">
        <h2 className="section-title">生成侧与延迟</h2>
        {extra.map((run) => (
          <article className="eval-round" id={run.id} key={run.id}>
            <div className="eval-round-head">
              <h3 className="eval-round-title">
                {run.id} · {run.title}
              </h3>
            </div>
            <div className="eval-run-id">{run.runId}</div>

            <dl className="eval-facts">
              <dt>测了什么</dt>
              <dd>{emphasise(run.changed)}</dd>
              <dt>结果</dt>
              <dd>{emphasise(run.finding)}</dd>
            </dl>

            <div className="eval-categories">
              {Object.entries(run.overall).map(([key, value]) => (
                <div className="eval-category" key={key}>
                  <div className="eval-category-name">{key}</div>
                  <div className="eval-category-value">
                    {typeof value === "number" ? Number(value.toFixed(4)) : String(value)}
                  </div>
                </div>
              ))}
            </div>
          </article>
        ))}
      </section>
    </>
  );
}

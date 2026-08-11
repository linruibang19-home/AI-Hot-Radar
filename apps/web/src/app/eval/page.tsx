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
  title: "检索评测",
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
  const { rounds, extra, goldenQuestions, ragas } = summary;
  const last = rounds[rounds.length - 1];
  const first = rounds[0];

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">检索评测</h1>
        <p className="page-subtitle">
          {goldenQuestions} 题黄金集 · 六类问题 · 每轮都有逐题 JSON 与判据 ·
          规格明写「先测 baseline 再加 reranker，不得只展示几个主观示例宣布有效」
        </p>
      </header>

      <div className="stat-row">
        <div className="stat">
          <div className="stat-value">{rounds.length}</div>
          <div className="stat-label">检索轮次</div>
        </div>
        <div className="stat">
          <div className="stat-value">{goldenQuestions}</div>
          <div className="stat-label">黄金集题量</div>
        </div>
        <div className="stat">
          <div className="stat-value">{metric(last.metrics.mrr)}</div>
          <div className="stat-label">当前 MRR</div>
        </div>
        <div className="stat">
          <div className="stat-value">{metric(last.metrics.recall10)}</div>
          <div className="stat-label">当前 Recall@10</div>
        </div>
      </div>

      <div className="notice">
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
          以及误拒率。反过来 <strong>Noise Sensitivity 诚实标注为未测</strong>——
          它需要构造带噪上下文的对照集，当前黄金集按真实语料标注，没有这个维度。
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

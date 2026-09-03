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
 * **Two populations, never merged.** The page opens on the gate and on the same
 * metrics recomputed over questions people actually asked, side by side. That
 * ordering is deliberate: 300 of the 400 lines here described how retrieval got
 * to where it is, and 60 described whether it currently works, which is the one
 * a reader arrives with. The rounds are still here in full, one disclosure down.
 *
 * The fixed set cannot be live and should not be: 90 questions, a frozen corpus
 * and a registered criterion are what make round N comparable to round N−1.
 * Live traffic is comparable to nothing — today's questions are not last
 * week's. Blending them would produce a number that means neither thing.
 *
 * Regenerate the round data with `python scripts/build_eval_summary.py`; the
 * live half comes from `/rag/stats` on every request.
 */

export const dynamic = "force-dynamic";

const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://ai-service:8000";

/** The gate's two metrics, recomputed over real traffic. See `ops.py`. */
interface LiveQuality {
  days: number;
  supportThreshold: number;
  queries: number;
  refused: number;
  refusalRate: number | null;
  answeredWithoutCitation: number;
  replayedFromCache: number;
  citations: number;
  supported: number;
  supportRate: number | null;
  supportMedian: number | null;
  servingModel: string | null;
  servingModels: { model: string; calls: number }[];
}

/** The gate's numbers, plus how much of today's corpus they were measured on. */
interface LiveState {
  quality: LiveQuality;
  corpusItems: number;
}

async function loadLive(): Promise<LiveState | null> {
  // The rounds render without it. A stats outage must not take down the record
  // of how retrieval got here.
  try {
    const response = await fetch(`${AI_SERVICE_URL}/rag/stats?days=30`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    const body = await response.json();
    const quality = body.quality as LiveQuality | undefined;
    if (!quality) return null;
    return { quality, corpusItems: Number(body.corpus?.items ?? 0) };
  } catch {
    return null;
  }
}

export const metadata: Metadata = {
  title: "RAG 质量",
  description:
    "发布门禁、线上实测，以及 90 题黄金集上的逐轮检索评测记录（含负结果）。",
};

/**
 * Over-refusal is a rate, not a zero.
 *
 * The gate demanded `over_refusal_rate === 0` — determinism from a stochastic
 * system. Four runs of the *same* image and prompt produced 2, 1, 1 and 3
 * over-refusals out of 78 answerable questions, and the failing questions were
 * a different set each time: 034 and 044, then 034, then 040, then 008, 032 and
 * 044. That is a per-question failure probability of about 2.24%, which makes
 * `(1 − 0.0224)^78 ≈ 17%` — the gate passed roughly one run in six on luck, and
 * a release could be blocked or cleared by nothing but the sampler.
 *
 * Measuring against a ceiling instead is the honest instrument. 5% allows three
 * of 78, comfortably above the observed mean of 1.75 and well below anything
 * that would indicate a real regression.
 *
 * The hard zero moves to where it belongs. Refusing a question you could have
 * answered is a quality loss; asserting something the corpus does not contain
 * is a safety failure, and `presupposition_asserted_rate` has been exactly 0.0
 * in every run ever recorded. That is a threshold this system can actually
 * hold.
 */
const OVER_REFUSAL_CEILING = 0.05;

/**
 * Refusal causes the model produces, which vary between identical runs.
 *
 * Anything not on this list came from the pipeline — the support gate emptying
 * the citations, an invariant failing, the credential policy firing, the
 * provider being down — and a pipeline that refuses is a defect however rarely
 * it happens. Those block regardless of the rate.
 */
const STOCHASTIC_CAUSES = ["all_sentences_uncited", "model_declined"];

const CAUSE_LABELS: Record<string, string> = {
  all_sentences_uncited: "模型漏标引用，整句被删",
  model_declined: "模型自己判定证据不足",
  all_citations_unsupported: "支持度校验移除了全部引用",
  invariant_violation: "引用校验未通过",
  credential_policy: "触发凭据输出保护",
  generation_unavailable: "生成服务不可用",
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
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .map((part, index) =>
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

export default async function EvalPage() {
  const { rounds, extra, goldenQuestions, ragas, release } = summary;
  const state = await loadLive();
  const live = state?.quality ?? null;
  // What share of today's corpus the frozen snapshot never sees. Derived on
  // every request, so it falls on its own as the corpus grows — which is
  // exactly the signal that the question set is due for a refresh.
  const uncovered =
    state && state.corpusItems > 0
      ? Math.max(0, 1 - release.snapshot.items / state.corpusItems)
      : null;
  const last = rounds[rounds.length - 1];
  const first = rounds[0];
  // The snapshot vouches for a named model. Nothing checked it against the one
  // answering, so the page went on certifying `deepseek-chat` while
  // `deepseek-v4-flash` wrote every answer — a gate that certifies a
  // configuration nobody runs certifies nothing.
  const modelDrifted =
    live?.servingModel != null &&
    live.servingModel !== release.snapshot.generationModel;
  // Refusals the model produced, which vary run to run, versus refusals the
  // pipeline produced, which do not. Only the second kind blocks a release.
  const codeSideCause = Object.keys(
    release.generation.over_refusal_causes ?? {},
  ).find((cause) => !STOCHASTIC_CAUSES.includes(cause));
  const releasePassed =
    release.retrieval["recall@20"] >= 0.85 &&
    release.generation.citation_coverage >= 0.95 &&
    release.generation.support_supported >= 0.9 &&
    release.generation.presupposition_asserted_rate === 0 &&
    release.generation.over_refusal_rate <= OVER_REFUSAL_CEILING &&
    codeSideCause === undefined &&
    release.specialist.passed;

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">RAG 质量</h1>
        <p className="page-subtitle">
          发布门禁与引用可靠性 · {goldenQuestions} 题黄金集
        </p>
      </header>

      <section className="quality-hero" aria-labelledby="release-gate-title">
        <div className="quality-hero-head">
          <div>
            <div className="eyebrow">CURRENT RELEASE GATE</div>
            <h2 id="release-gate-title">
              当前 RAG {releasePassed ? "达到发布门槛" : "未达到发布门槛"}
            </h2>
          </div>
          <span
            className={`state ${releasePassed ? "verdict-pass" : "verdict-mixed"}`}
          >
            {releasePassed ? "可发布" : "需阻断"}
          </span>
        </div>
        {/* One line, not a paragraph. What a reader needs before the numbers
            mean anything is the corpus date and the models — the rest of the
            methodology moved into the disclosure below the tiles. */}
        <div className="quality-snapshot" aria-label="当前发布评测快照">
          <div>
            <strong>静态发布评测</strong>
            <span>
              语料截止 {release.snapshot.cutoff.slice(0, 10)} ·{" "}
              {release.snapshot.items} 条内容
            </span>
          </div>
          <div>
            <span>{release.snapshot.embeddingModel}</span>
            <span>{release.snapshot.rerankerModel}</span>
            <span>{release.snapshot.generationModel}</span>
          </div>
        </div>
        {/* How much of today's corpus the frozen set never sees. The panel said
            「915 条内容」 and stopped there, so a reader could not tell that the
            number had become a third of the library. It falls on its own as
            ingestion continues, which is the refresh signal. */}
        {uncovered !== null && state && (
          <p className="quality-coverage">
            这 {release.snapshot.items} 条是标注当时的语料。全库现在有{" "}
            <strong>{state.corpusItems.toLocaleString()}</strong> 条，
            <strong>{percent(uncovered)}</strong> 从未参与过评测——门禁能证明
            <strong>检索与引用机制没退步</strong>
            ，不能证明新语料上的回答是对的。 那一半由下面的线上实测覆盖。
          </p>
        )}
        {modelDrifted && (
          <p className="quality-drift" role="alert">
            <strong>快照与线上不一致。</strong>
            上面的门禁结论是在 <code>
              {release.snapshot.generationModel}
            </code>{" "}
            上跑出来的， 而近 {live?.days} 天实际回答问题的是{" "}
            <code>{live?.servingModel}</code>。
            生成模型换了就必须重跑生成回归——在重跑并发布新快照之前，
            <strong>这块门禁不能代表线上正在跑的配置</strong>。
          </p>
        )}
        {/* Folded, not deleted. Eight blocks stood between the headline and the
            numbers, every one of them a paragraph defending the number that
            followed it — the signature of a page that answered each "what does
            this mean?" by appending prose instead of by making the number
            legible. Everything a sceptic needs is still one click away; the
            reader who wants the verdict now gets it without scrolling. */}
        <details className="quality-method">
          <summary>这些数字是怎么来的</summary>
          <div className="quality-method-body">
            <p>
              这不是主观评分：主检索、90 题生成与中文厂商噪声专项分别绑定到可追溯
              run。
              自动引用精度受稀疏标注影响，只作诊断；发布正确性采用段落支持门与人工
              P0 审计。
            </p>
            <p>
              <strong>这块快照不会随线上提问变化，这是评测的定义</strong>
              ：题集、语料、判据三者固定，轮次之间才可比。
              切换模型、提示词、切块或检索策略后，必须重跑固定黄金集并发布新快照。
              真实提问下的表现见下一节；请求成本与延迟见{" "}
              <a href="/ops">运行状态</a>。
            </p>
            <div className="quality-run-ids">
              <code>{release.retrievalRunId}</code>
              <code>{release.generationRunId}</code>
              <code>{release.specialistRunId}</code>
            </div>
          </div>
        </details>
      </section>

      <div className="stat-row">
        <div className="stat">
          <div className="stat-value">
            {percent(release.retrieval["recall@20"])}
          </div>
          <div className="stat-label">主集 Recall@20 · 门槛 85%</div>
        </div>
        <div className="stat">
          <div className="stat-value">
            {percent(release.generation.citation_coverage)}
          </div>
          <div className="stat-label">事实句引用完整性 · 门槛 95%</div>
        </div>
        <div className="stat">
          <div className="stat-value">
            {percent(release.generation.support_supported)}
          </div>
          <div className="stat-label">段落支持达标率 · 门槛 90%</div>
        </div>
        {/* Derived, not written. Both tiles said 「0 /」 as a literal, which was
            true when the gate demanded zero and became a lie the moment the
            threshold moved — on the page whose whole claim is being exact about
            what was measured. */}
        <div className="stat">
          <div className="stat-value">
            {Math.round(
              release.generation.over_refusal_rate *
                release.generation.answerable,
            )}{" "}
            / {release.generation.answerable}
          </div>
          <div className="stat-label">
            可答题误拒 · 上限 {percent(OVER_REFUSAL_CEILING)}
          </div>
        </div>
        <div className="stat">
          <div className="stat-value">
            {Math.round(
              release.generation.presupposition_asserted_rate *
                release.generation.unanswerable,
            )}{" "}
            / {release.generation.unanswerable}
          </div>
          <div className="stat-label">诱导题错误断言 · 门槛 0</div>
        </div>
      </div>

      {/* Why the ceiling is not zero, stated where the number is. A threshold
          that looks lax needs its reasoning attached, or the next person tightens
          it back to zero and spends a week re-deriving why that does not work. */}
      {release.generation.over_refusal_causes && (
        <div className="notice">
          <strong>误拒为什么不是硬门禁 0。</strong>
          同一镜像、同一提示词连跑四次，误拒分别是{" "}
          <strong>2 / 1 / 1 / 3</strong> 道，
          失败的题每次都换一批——单题误拒概率约 <strong>2.24%</strong>，78
          题全过的概率只有 约 <strong>17%</strong>
          。要求一个随机系统给出确定性结果，等于让发布靠运气。 硬门禁留给
          <strong>诱导题错误断言</strong>
          ：编造是安全失败，而它在历次记录中始终为 0。
          <div className="eval-causes">
            {Object.entries(release.generation.over_refusal_causes).map(
              ([cause, count]) => (
                <span
                  key={cause}
                  className={
                    STOCHASTIC_CAUSES.includes(cause)
                      ? "eval-cause"
                      : "eval-cause is-blocking"
                  }
                >
                  {CAUSE_LABELS[cause] ?? cause}
                  <b>{count}</b>
                </span>
              ),
            )}
          </div>
          <span className="eval-cause-note">
            模型侧的零散失误计入上限；流水线自身产生的拒答（支持度清空、引用校验失败、
            凭据保护、生成服务不可用）不论多少次都直接阻断发布。
          </span>
        </div>
      )}

      {/* The same two metrics over a different population. Deliberately a
          comparison table rather than one blended figure: the fixed set is what
          makes rounds comparable, real traffic is what says whether the fixed
          set still resembles what the system is asked, and a single number
          would answer neither question. */}
      {live && live.queries > 0 && (
        <section className="eval-section" aria-labelledby="live-quality-title">
          <h2 className="section-title" id="live-quality-title">
            线上实测 · 近 {live.days} 天
          </h2>
          <p className="eval-note">
            门禁的两个指标，换成<strong>人们真的问出来的问题</strong>
            重新算一遍。
            左边固定、可比，是判断「改动有没有让质量退步」的依据；右边实时、不可比，
            是判断「固定题集还像不像真实提问」的依据。两边都不能替代对方，所以不合并成一个分数。
          </p>
          <div className="table-scroll">
            <table className="table eval-table">
              <thead>
                <tr>
                  <th>指标</th>
                  <th>固定评测 · {goldenQuestions} 题黄金集</th>
                  <th>线上实测 · {live.queries} 次真实提问</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <strong>拒答</strong>
                    <div className="eval-meta">
                      黄金集只统计「标注为可答却被拒」；线上没有标注，其中一部分拒答是对的
                    </div>
                  </td>
                  <td className="eval-num">
                    {release.generation.over_refusal_rate === 0
                      ? `0 / ${release.generation.answerable}`
                      : percent(release.generation.over_refusal_rate)}
                  </td>
                  <td className="eval-num">
                    {live.refusalRate === null
                      ? "—"
                      : percent(live.refusalRate)}
                    <div className="eval-meta">
                      {live.refused} / {live.queries}
                    </div>
                  </td>
                </tr>
                <tr>
                  <td>
                    <strong>引用支持度达标率</strong>
                    <div className="eval-meta">
                      交叉编码器对「论断 × 被引段落」打分 ≥{" "}
                      {live.supportThreshold}
                    </div>
                  </td>
                  <td className="eval-num">
                    {percent(release.generation.support_supported)}
                  </td>
                  <td className="eval-num">
                    {live.supportRate === null
                      ? "—"
                      : percent(live.supportRate)}
                    <div className="eval-meta">
                      {live.supported} / {live.citations}
                      {live.supportMedian !== null &&
                        ` · 中位数 ${live.supportMedian}`}
                    </div>
                  </td>
                </tr>
                <tr>
                  <td>
                    <strong>无引用的回答</strong>
                    <div className="eval-meta">
                      不是拒答，也不在门禁的统计里——它长得像正常回答，却没有可核对的东西
                    </div>
                  </td>
                  <td className="eval-num">—</td>
                  <td className="eval-num">{live.answeredWithoutCitation}</td>
                </tr>
                <tr>
                  <td>
                    <strong>语料</strong>
                    <div className="eval-meta">
                      黄金集固定在标注当时的语料，否则标注会随语料失效、重跑也不可复现
                    </div>
                  </td>
                  <td className="eval-num">
                    {release.snapshot.items} 条 · 冻结于{" "}
                    {release.snapshot.cutoff.slice(0, 10)}
                  </td>
                  <td className="eval-num">实时</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="eval-note">
            其中 <strong>{live.replayedFromCache}</strong>{" "}
            次由缓存直接重放，没有调用模型。
            候选去向、通道归因与重排深度这些检索侧的线上统计在{" "}
            <a href="/ops">运行状态</a>，不在这里重复。
          </p>
        </section>
      )}

      {/* Was three numbered cards. Two of them restated the tiles directly
          above — Recall@20 and the two generation gates — and numbering 01/02/03
          implied a sequence that did not exist; they are parallel claims, not
          steps. What survives is the only card that said something the numbers
          could not: what these numbers still do not cover. */}
      <p className="quality-limits">
        <strong>这些数字没覆盖到的：</strong>
        中文厂商噪声结论目前只有 15 题专项样本；每次切换生成模型后必须重跑生成回归；
        自动引用精度不能替代人工高风险数字审计。
      </p>

      {/* Folded, not deleted.
          These four sections were 300 of the page's 400 lines and everything a
          reader arrives asking — does it work now, and on the model that is
          actually running — was underneath them. They are the argument that the
          current numbers were earned rather than tuned into place, which is
          worth one click and is not worth the top of the page. */}
      <details className="eval-archive">
        <summary className="eval-archive-title">
          算法演进记录
          <span className="eval-archive-note">
            {rounds.length} 轮检索评测 · RAGAS 术语对照 · 生成侧与延迟 · 含 3
            轮负结果
          </span>
        </summary>

        <div className="notice">
          <strong>下面是算法演进记录，不是当前发布快照。</strong>
          <br />从 <strong>{first.id} 纯稠密</strong>（MRR{" "}
          {metric(first.metrics.mrr)}）到 <strong>{last.id}</strong>（MRR{" "}
          {metric(last.metrics.mrr)}），提升{" "}
          {(((last.metrics.mrr ?? 0) - (first.metrics.mrr ?? 0)) * 100).toFixed(
            1,
          )}{" "}
          个点。 这里保留了三轮「不好看」的结果：
          <strong>B2 的并集比基线还差</strong>、
          <strong>B8 扫完 42 组权重后的结论是不改</strong>，以及{" "}
          <strong>B13 修好中文分词后端到端 ±0.0000</strong>。
          只展示赢的那几轮，这页就不是评测记录而是宣传页。
          下面「生成侧与延迟」里还有一条：GEN 写下的
          <strong>假设被 GEN-FIX 证伪</strong>， 两轮都留着。
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
                      <td className="eval-changed">
                        {emphasise(round.changed)}
                      </td>
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
                        <div className="eval-delta">
                          {delta(round.metrics.mrr, prior?.mrr)}
                        </div>
                      </td>
                      <td className="eval-num">
                        {metric(round.metrics.ndcg10)}
                        <div className="eval-delta">
                          {delta(round.metrics.ndcg10, prior?.ndcg10)}
                        </div>
                      </td>
                      <td>
                        <span className={`state ${verdict.className}`}>
                          {verdict.label}
                        </span>
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
                  <span className={`state ${verdict.className}`}>
                    {verdict.label}
                  </span>
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
                    {metric(round.alt.metrics.recall10)} · MRR{" "}
                    {metric(round.alt.metrics.mrr)} · nDCG@10{" "}
                    {metric(round.alt.metrics.ndcg10)}
                  </p>
                )}

                {Object.keys(round.byCategory).length > 0 && (
                  <div className="eval-categories">
                    {Object.entries(round.byCategory).map(([name, row]) => (
                      <div className="eval-category" key={name}>
                        <div className="eval-category-name">
                          {CATEGORIES[name] ?? name}
                        </div>
                        <div className="eval-category-value">
                          MRR {metric(row.mrr)}
                        </div>
                        <div className="eval-category-sub">
                          R@10 {metric(row.recall10)}
                        </div>
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
            三项没有 RAGAS 对应：<strong>story_coverage</strong>（RAGAS
            假设文档彼此独立， 而四家媒体报道同一次披露是<strong>一条</strong>
            证据不是四条）、
            <strong>citation_coverage</strong>
            （句级引用覆盖率是本项目的核心主张）、 以及误拒率。Noise Sensitivity
            目前采用 15 题中文厂商专项集与 8 个真实近邻噪声 做同候选快照
            A/B；它已经覆盖最容易串线的场景，但仍只是专项小样本， 不能冒充完整
            90 题噪声回归。
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
                      {typeof value === "number"
                        ? Number(value.toFixed(4))
                        : String(value)}
                    </div>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </section>
      </details>
    </>
  );
}

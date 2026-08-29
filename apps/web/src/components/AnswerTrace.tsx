import type { AnswerPayload, TraceRow } from "@/components/AskPanel";
import { formatDateTime } from "@/lib/datetime";

/**
 * One answer's whole pipeline, as one line you can open.
 *
 * This replaces two panels that split the same chain in half. 「检索过程」 drew
 * four ticks from the SSE progress events and 「为什么是这几条证据」 drew a
 * forty-row table from `rag_trace`, so a reader following the funnel had to
 * open two disclosures and reconcile them by eye — and they did not reconcile:
 * one said 「101 条候选」 and the other 「40 个候选」, which are both true and
 * name different stages. They are one funnel here, with every step named:
 *
 *     召回 101 → 重排 40 → 证据 10 → 引用 4
 *
 * The summary line is *not* inside the disclosure. Collapsing the whole chain
 * behind a click is the black box this feature exists to remove; forty rows
 * open by default on every turn is a different kind of unreadable. The line
 * states the funnel, the disclosure holds the evidence for it.
 *
 * Everything above comes from `metrics` and `trace`, both of which are stored
 * with the answer. The SSE stage events are used only while a question is in
 * flight — reading them afterwards is what made the permalink show a panel with
 * no timings, since a stored answer never replays its progress stream.
 */

const OUTCOMES: Record<string, { label: string; className: string; hint: string }> = {
  cited: {
    label: "被引用",
    className: "trace-cited",
    hint: "进入证据集，并且答案里确实引用了它",
  },
  evidence_uncited: {
    label: "未引用",
    className: "trace-evidence",
    hint: "模型读到了它，但没有在答案里引用——通常是它没有回答这个问题",
  },
  dropped_document_cap: {
    label: "同篇超额",
    className: "trace-dropped",
    hint: "同一篇文档已经占了 2 段。一篇文档无论多长，仍然只是一个来源",
  },
  dropped_source_cap: {
    label: "同信源超额",
    className: "trace-dropped",
    hint: "同一家信源已占满 3 段。一家媒体发多少篇，都只是一家的说法",
  },
  dropped_story_fold: {
    label: "同事件折叠",
    className: "trace-dropped",
    hint: "同一事件已有其他信源入选。独立性按信源计，不按文章计",
  },
  dropped_budget: {
    label: "预算已满",
    className: "trace-dropped",
    hint: "证据位被前面的候选占满了，它本身没有被判为冗余",
  },
  ranked_out: {
    label: "未进证据",
    className: "trace-out",
    hint: "排序没能把它送进证据集",
  },
};

/* §6 的五条调整，展开成读者能核对的说法。Keys are the labels `fusion.py`
   writes, not a parallel vocabulary — a mismatch renders the raw key and
   silently stops explaining anything, which is how `primary` shipped against
   an emitter that writes `primary_source`. */
const BOOSTS: Record<string, string> = {
  primary_source: "一手信源 +0.08",
  in_time_window: "落在时间窗内 +0.05",
  entity_subject: "问题实体是主语 +0.05",
  repost: "疑似转载 −0.10",
  opinion_for_fact: "观点用于事实题 −0.15",
};

/**
 * Stage names, for the breakdown that is derived rather than declared.
 *
 * A fixed list of four was tried first and 「其他」 came out the largest bar on
 * the first real answer — 5488ms of 15.0s, more than generation. A breakdown
 * whose biggest row is 「everything I did not name」 explains nothing. The bar
 * is built from `stages_ms` itself now, so a stage added to the pipeline shows
 * up here without anyone remembering to add it.
 */
const STAGE_LABELS: Record<string, string> = {
  plan: "理解问题",
  embed: "向量化",
  dense: "稠密召回",
  sparse: "关键词召回",
  fuse: "融合排序",
  rerank: "重排",
  select: "证据筛选",
  parent: "扩展母块",
  generate: "生成",
  support: "支持度校验",
  numeric_audit: "数字核对",
};

/** Stages below this share of the total are summed rather than listed; six
    rows is the point past which a legend stops being read. */
const TIMING_FLOOR = 0.02;
const TIMING_ROWS = 6;

const QUERY_TYPES: Record<string, string> = {
  recent_updates: "最新动态",
  timeline: "时间线",
  comparison: "对比",
  fact_check: "事实核查",
  explainer: "原理解释",
  abstention: "开放提问",
};

function rank(value: number | null) {
  return value === null ? <span className="trace-none">—</span> : <>#{value}</>;
}

function score(value: number | null) {
  return value === null ? "" : value.toFixed(4);
}

/** The four-step list, shown only while a question is still running. */
export function LiveProgress({ stages }: { stages: { stage: string; started?: boolean }[] }) {
  const STEPS = [
    { key: "plan", label: "理解问题" },
    { key: "embed", label: "检索证据" },
    { key: "rerank", label: "重排候选" },
    { key: "generate", label: "生成回答" },
  ];
  // A stage that has only *started* is not done. `generate` is the whole point
  // of the distinction: it reports at its beginning and takes 5.7s at p50, so
  // treating any reported stage as complete draws four ticks and then leaves
  // the reader watching a finished checklist for six seconds.
  const done = new Set(stages.filter((s) => !s.started).map((s) => s.stage));
  const running = stages.filter((s) => s.started).map((s) => s.stage);

  return (
    <ol className="live-steps" aria-live="polite">
      {STEPS.map((step, index) => {
        const isDone = done.has(step.key);
        const active =
          !isDone &&
          (running.includes(step.key) ||
            STEPS.filter((s) => done.has(s.key)).length === index);
        return (
          <li
            key={step.key}
            className={`live-step${isDone ? " is-done" : ""}${active ? " is-active" : ""}`}
          >
            {step.label}
          </li>
        );
      })}
    </ol>
  );
}

export function AnswerTrace({ turn }: { turn: AnswerPayload }) {
  const rows: TraceRow[] = turn.trace ?? [];
  const metrics = turn.metrics ?? {};
  const cache = metrics.cache;
  const cached = Boolean(cache?.outcome && cache.outcome !== "miss");

  // The funnel, each number from the stage that produced it. `fused` and the
  // rerank window were the two that used to be shown side by side as if they
  // were the same quantity.
  const recalled = metrics.fused ?? null;
  const reranked = rows.length || null;
  const evidence = metrics.evidence ?? null;
  const cited = turn.citations.length;

  const rescued = rows.filter(
    (r) => r.fusedRank !== null && r.rerankRank !== null && r.rerankRank < r.fusedRank,
  ).length;
  const sparseOnly = rows.filter((r) => r.denseRank === null && r.sparseRank !== null).length;

  // Default to the passages that reached the model. The other thirty are the
  // answer to "why not that article", which is a question a reader asks second.
  const inEvidence = rows.filter(
    (r) => r.outcome === "cited" || r.outcome === "evidence_uncited",
  );

  const timings = metrics.stages_ms ?? {};
  const totalMs = metrics.total_ms ?? 0;
  const ranked = Object.entries(timings)
    .map(([key, ms]) => ({ key, label: STAGE_LABELS[key] ?? key, ms }))
    .filter((t) => t.ms > 0)
    .sort((a, b) => b.ms - a.ms);
  const named = ranked
    .slice(0, TIMING_ROWS)
    .filter((t) => !totalMs || t.ms / totalMs >= TIMING_FLOOR);
  // Whatever is left, including the time between stages — connection setup,
  // persistence, the JSON on the wire. Stating it is honest; it is only a
  // problem when it is the largest bar, which is what a hard-coded list of
  // four stages made it.
  const other = Math.max(0, totalMs - named.reduce((sum, t) => sum + t.ms, 0));

  if (!rows.length && !totalMs) return null;

  return (
    <details className="funnel">
      <summary className="funnel-line">
        <span className="funnel-steps">
          {recalled !== null && (
            <>
              <span>
                召回 <b>{recalled}</b>
              </span>
              <i aria-hidden="true">→</i>
            </>
          )}
          {reranked !== null && (
            <>
              <span>
                重排 <b>{reranked}</b>
              </span>
              <i aria-hidden="true">→</i>
            </>
          )}
          {evidence !== null && (
            <>
              <span>
                证据 <b>{evidence}</b>
              </span>
              <i aria-hidden="true">→</i>
            </>
          )}
          <span>
            引用 <b>{cited}</b>
          </span>
        </span>
        <span className="funnel-aside">
          {cached
            ? cache?.outcome === "semantic"
              ? "命中语义缓存"
              : "命中缓存"
            : totalMs
              ? `${(totalMs / 1000).toFixed(1)}s`
              : null}
        </span>
        <span className="funnel-more">全过程</span>
      </summary>

      <div className="funnel-body">
        {named.length > 0 && (
          <section className="funnel-part">
            <h4>耗时分布</h4>
            <div className="funnel-bar" aria-hidden="true">
              {named.map((t, index) => (
                <span
                  key={t.key}
                  className={`funnel-seg seg-${index + 1}`}
                  style={{ flexGrow: t.ms }}
                  title={`${t.label} ${t.ms}ms`}
                />
              ))}
              {other > 0 && <span className="funnel-seg seg-other" style={{ flexGrow: other }} />}
            </div>
            <ul className="funnel-legend">
              {named.map((t, index) => (
                <li key={t.key}>
                  <i className={`seg-${index + 1}`} aria-hidden="true" />
                  {t.label}
                  <b>{t.ms}ms</b>
                </li>
              ))}
              {other > 0 && (
                <li>
                  <i className="seg-other" aria-hidden="true" />
                  其他
                  <b>{other}ms</b>
                </li>
              )}
            </ul>
          </section>
        )}

        <section className="funnel-part">
          <h4>关键决策</h4>
          <dl className="funnel-facts">
            {turn.rewrittenQuestion && (
              <>
                <dt>追问改写</dt>
                <dd>{turn.rewrittenQuestion}</dd>
              </>
            )}
            {turn.plan?.query_type && (
              <>
                <dt>问题类型</dt>
                <dd>{QUERY_TYPES[turn.plan.query_type] ?? turn.plan.query_type}</dd>
              </>
            )}
            <dt>时间窗</dt>
            <dd>
              {turn.plan?.time_range?.from && turn.plan?.time_range?.to
                ? `${turn.plan.time_range.from.slice(0, 10)} – ${turn.plan.time_range.to.slice(0, 10)}`
                : "全部时间"}
            </dd>
            {metrics.channels && (
              <>
                <dt>双通道召回</dt>
                <dd>
                  稠密 {metrics.channels.dense ?? 0} · 关键词 {metrics.channels.sparse ?? 0} → 融合{" "}
                  {recalled ?? 0}
                  {sparseOnly > 0 && (
                    <span className="funnel-hint">
                      其中 {sparseOnly} 条只有关键词通道召回到——纯语义检索会把 MXFP4 召回成 NVFP4
                    </span>
                  )}
                </dd>
              </>
            )}
            {metrics.aliases && metrics.aliases.length > 0 && (
              <>
                <dt>别名扩展</dt>
                <dd>{metrics.aliases.join(" · ")}</dd>
              </>
            )}
            {metrics.selection?.distinct_sources != null && (
              <>
                <dt>信源去重</dt>
                <dd>
                  证据集覆盖 {metrics.selection.distinct_sources} 家信源
                  {metrics.selection.source_capped
                    ? `，另有 ${metrics.selection.source_capped} 条因同信源超额被丢弃`
                    : ""}
                </dd>
              </>
            )}
            {rescued > 0 && (
              <>
                <dt>重排救回</dt>
                <dd>{rescued} 条候选的排名被交叉编码器提前</dd>
              </>
            )}
            {metrics.support_dropped ? (
              <>
                <dt>支持度校验</dt>
                <dd>移除了 {metrics.support_dropped} 条支持度不足的引用</dd>
              </>
            ) : null}
            {turn.askedAt && (
              <>
                <dt>检索截至</dt>
                <dd>{formatDateTime(turn.askedAt)}（只依据此刻前已入库的内容）</dd>
              </>
            )}
            {metrics.degraded && metrics.degraded.length > 0 && (
              <>
                <dt>降级</dt>
                <dd className="funnel-warn">{metrics.degraded.join("、")}</dd>
              </>
            )}
          </dl>
        </section>

        {rows.length > 0 && (
          <section className="funnel-part">
            <h4>
              候选去向
              <span className="funnel-sub">
                两个通道各自召回 → RRF 融合 → §6 元数据调整 → 交叉编码器重排 → 每篇/每信源限流 →
                同事件折叠 → 预算截断
              </span>
            </h4>
            <CandidateTable rows={inEvidence} />
            {rows.length > inEvidence.length && (
              <details className="funnel-all">
                <summary>展开全部 {rows.length} 条候选，含被淘汰的</summary>
                <CandidateTable rows={rows} />
                <p className="funnel-note">
                  <strong>同篇超额</strong>拦的是一篇文档的多个段落，<strong>同信源超额</strong>
                  拦的是一家媒体的多篇报道，<strong>同事件折叠</strong>
                  拦的是多家媒体对同一件事的报道。三者在答案里长得一样，含义完全不同。
                </p>
              </details>
            )}
          </section>
        )}
      </div>
    </details>
  );
}

function CandidateTable({ rows }: { rows: TraceRow[] }) {
  return (
    <div className="table-scroll">
      <table className="table trace-table">
        <thead>
          <tr>
            <th>段落</th>
            <th>稠密</th>
            <th>关键词</th>
            <th>融合</th>
            <th>重排</th>
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const outcome = OUTCOMES[row.outcome] ?? OUTCOMES.ranked_out;
            return (
              <tr key={row.chunkId} className={outcome.className}>
                <td>
                  {row.itemId ? (
                    <a href={`/items/${row.itemId}`}>{row.title || "（无标题）"}</a>
                  ) : (
                    row.title || "（无标题）"
                  )}
                  <div className="trace-meta">
                    {row.sourceName}
                    {row.channels && ` · ${row.channels}`}
                  </div>
                  {row.boosts.length > 0 && (
                    <div className="trace-boosts">
                      {row.boosts.map((b) => (
                        <span key={b} className="trace-boost">
                          {BOOSTS[b] ?? b}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="trace-num">
                  {rank(row.denseRank)}
                  <div className="trace-score">{score(row.denseScore)}</div>
                </td>
                <td className="trace-num">
                  {rank(row.sparseRank)}
                  <div className="trace-score">{score(row.sparseScore)}</div>
                </td>
                <td className="trace-num">
                  {rank(row.fusedRank)}
                  <div className="trace-score">{score(row.fusedScore)}</div>
                </td>
                <td className="trace-num">
                  {rank(row.rerankRank)}
                  <div className="trace-score">{score(row.rerankScore)}</div>
                </td>
                <td>
                  <span className={`state ${outcome.className}`} title={outcome.hint}>
                    {outcome.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

import type { TraceRow } from "@/components/AskPanel";

/**
 * Why these passages and not the others.
 *
 * An answer shows which passages it used. The question anyone debugging a wrong
 * answer asks first is the one it could not show: what else was in the running,
 * how far did it get, and what removed it. Every number here was computed while
 * the query ran and discarded at the next hand-off until `rag_trace` gave it a
 * home.
 *
 * Read as a funnel: two channels propose, RRF merges, §6 adjusts, the
 * cross-encoder reorders, then two different de-duplication rules and a budget
 * cut it to ten. A row shows where each candidate left.
 */

const OUTCOMES: Record<string, { label: string; className: string; hint: string }> = {
  cited: {
    label: "被引用",
    className: "trace-cited",
    hint: "进入证据集，并且答案里确实引用了它",
  },
  evidence_uncited: {
    label: "进证据未引用",
    className: "trace-evidence",
    hint: "模型读到了它，但没有在答案里引用——通常是它没有回答这个问题",
  },
  dropped_document_cap: {
    label: "同篇超额",
    className: "trace-dropped",
    hint: "同一篇文档已经占了 2 段。一篇文档无论多长，仍然只是一个来源",
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

function rank(value: number | null) {
  return value === null ? <span className="trace-none">—</span> : <>#{value}</>;
}

function score(value: number | null) {
  return value === null ? "" : value.toFixed(4);
}

export function RetrievalTrace({ rows }: { rows: TraceRow[] }) {
  if (!rows.length) return null;

  const cited = rows.filter((r) => r.outcome === "cited").length;
  const rescued = rows.filter(
    (r) => r.fusedRank !== null && r.rerankRank !== null && r.rerankRank < r.fusedRank,
  ).length;
  const sparseOnly = rows.filter((r) => r.denseRank === null && r.sparseRank !== null).length;

  return (
    <details className="ask-trace trace-panel">
      <summary className="ask-trace-summary">
        为什么是这几条证据
        <span className="ask-step-detail">{rows.length} 个候选</span>
        <span className="ask-step-detail">{cited} 条被引用</span>
        {rescued > 0 && <span className="ask-step-detail">重排救回 {rescued} 条</span>}
      </summary>

      <p className="trace-note">
        两个通道各自召回 → RRF 融合 → §6 元数据调整 → 交叉编码器重排 → 每篇限流 →
        同事件折叠 → 预算截断。
        {sparseOnly > 0 && (
          <>
            {" "}
            其中 <strong>{sparseOnly}</strong> 条只有关键词通道召回到——
            这正是混合检索存在的理由（纯语义会把 MXFP4 召回成 NVFP4）。
          </>
        )}
      </p>

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
                          <span key={b} className="trace-boost" title={BOOSTS[b] ?? b}>
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

      <p className="trace-note trace-legend">
        <strong>同篇超额</strong>与<strong>同事件折叠</strong>是两条不同的规则：前者拦的是
        一篇文档的多个段落，后者拦的是多家媒体对同一件事的报道。两者在答案里长得一样，
        含义完全不同，所以分开记录。
      </p>
    </details>
  );
}

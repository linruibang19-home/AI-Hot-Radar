import type { Metadata } from "next";

/**
 * Cost and latency, from production rows rather than a benchmark.
 *
 * The offline latency run sampled 24 questions on one afternoon. This is every
 * question anyone has actually asked, which is a different and more honest
 * distribution — it includes the slow tail that a benchmark schedules away.
 *
 * Money is labelled an estimate throughout, because the provider reports tokens
 * and a configured price table converts them. Tokens are provider-reported and
 * are not estimates; the two must not be presented as equally solid.
 */

export const metadata: Metadata = {
  title: "成本与延迟",
  description: "真实运行数据：provider 上报的 token、按配置价目表估算的成本、线上 p50/p95。",
};

export const dynamic = "force-dynamic";

const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://ai-service:8000";

interface Stats {
  cost: {
    days: number;
    rates: Record<string, number>;
    operations: {
      operation: string;
      model: string;
      calls: number;
      promptTokens: number;
      completionTokens: number;
      cachedTokens: number;
      failed: number;
      avgLatencyMs: number;
      estimatedCny: number;
      cnyPerCall: number;
    }[];
    totalEstimatedCny: number;
  };
  latency: {
    days: number;
    queries: number;
    p50Ms: number;
    p95Ms: number;
    maxMs: number;
    refused: number;
    refusalRate: number;
    stages: { stage: string; samples: number; p50Ms: number; shareOfP50: number }[];
  };
  retrieval: {
    days: number;
    queries: number;
    candidates: number;
    outcomes: { outcome: string; count: number }[];
    citedByChannel: Record<string, number>;
    sparseOnlyShare: number | null;
    citedFusedRankMedian: number | null;
    citedFusedRankMax: number | null;
    citedBeyondTop10: number;
  };
  cache: {
    counts: Record<string, number>;
    indexed: number;
    threshold: number;
    answerTtlSeconds: number;
    hitRate: number;
    embeddingHitRate: number;
  };
  corpus: {
    items: number;
    chunks: number;
    embedded: number;
    activeSources: number;
    citations: number;
    multiSourceStories: number;
  };
}

const OPERATIONS: Record<string, string> = {
  enrich: "内容结构化",
  recommend: "推荐理由",
  rag_answer: "RAG 问答生成",
};

const STAGES: Record<string, string> = {
  plan: "查询规划",
  embed: "问题嵌入",
  dense: "稠密召回",
  sparse: "关键词召回",
  fuse: "RRF 融合",
  rerank: "交叉编码器重排",
  select: "证据选择",
  parent: "父块展开",
  generate: "生成回答",
  support: "引用支持度打分",
  cache: "缓存查询",
};

/** What each trace outcome means. The three "dropped" reasons are recorded
    separately because they are different decisions — collapsing them into one
    `dropped` would make "which stage should I tune" unanswerable. */
const OUTCOMES: Record<string, string> = {
  cited: "进入证据集，且答案引用了它",
  evidence_uncited: "进入证据集，但答案没用上",
  dropped_document_cap: "同一篇文章已超额（单篇霸榜保护）",
  dropped_story_fold: "同一事件已有代表（四家媒体报道同一件事只算一条）",
  dropped_budget: "证据位已满（上限 10 条）",
  ranked_out: "重排后排名不够靠前",
};

/** The stages that leave the machine. Everything else is local SQL.
    `support` is a reranker call per citation, issued concurrently. */
const EXTERNAL = new Set(["embed", "rerank", "generate", "support"]);

async function load(): Promise<Stats | null> {
  try {
    const response = await fetch(`${AI_SERVICE_URL}/rag/stats?days=30`, { cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as Stats;
  } catch {
    return null;
  }
}

function ms(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

export default async function OpsPage() {
  const stats = await load();

  if (!stats) {
    return (
      <>
        <header className="page-head">
          <h1 className="page-title">成本与延迟</h1>
        </header>
        <div className="empty">暂时读不到运行统计。</div>
      </>
    );
  }

  const { cost, latency, corpus, cache, retrieval } = stats;
  const externalMs = latency.stages
    .filter((s) => EXTERNAL.has(s.stage))
    .reduce((sum, s) => sum + s.p50Ms, 0);
  const localMs = latency.stages
    .filter((s) => !EXTERNAL.has(s.stage))
    .reduce((sum, s) => sum + s.p50Ms, 0);
  const externalShare = latency.p50Ms ? externalMs / (externalMs + localMs) : 0;

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">成本与延迟</h1>
        <p className="page-subtitle">
          近 {cost.days} 天 · token 由 provider 上报（非字符估算）· 金额按配置价目表换算 ·
          延迟取自每一次真实提问，不是基准测试
        </p>
      </header>

      <div className="stat-row">
        <div className="stat">
          <div className="stat-value">¥{cost.totalEstimatedCny.toFixed(2)}</div>
          <div className="stat-label">估算总成本</div>
        </div>
        <div className="stat">
          <div className="stat-value">{latency.queries}</div>
          <div className="stat-label">问答次数</div>
        </div>
        <div className="stat">
          <div className="stat-value">{ms(latency.p50Ms)}</div>
          <div className="stat-label">p50 延迟</div>
        </div>
        <div className="stat">
          <div className="stat-value">{ms(latency.p95Ms)}</div>
          <div className="stat-label">p95 延迟</div>
        </div>
      </div>

      <div className="notice">
        <strong>金额是估算，token 不是。</strong> provider 只上报 token 数，
        换算成钱要用价目表，而价目表是会变的合同条款——所以它放在配置里
        （当前 输入 ¥{cost.rates.input}/M · 命中缓存 ¥{cost.rates.cached_input}/M · 输出 ¥
        {cost.rates.output}/M），不写死在代码里。
        <br />
        <br />
        <strong>而这三个值目前是占位默认值，不是任何 provider 的真实费率。</strong>
        上线前必须按现行价目设置 <code>LLM_PRICE_INPUT</code> /{" "}
        <code>LLM_PRICE_CACHED_INPUT</code> / <code>LLM_PRICE_OUTPUT</code>，
        否则本节每一个金额都是假的——一个看起来精确的错数字，比没有数字更坏。
      </div>

      <section className="eval-section">
        <h2 className="section-title">按操作分解</h2>
        <div className="table-scroll">
          <table className="table eval-table">
            <thead>
              <tr>
                <th>操作</th>
                <th>调用</th>
                <th>输入 token</th>
                <th>其中命中缓存</th>
                <th>输出 token</th>
                <th>平均延迟</th>
                <th>估算成本</th>
                <th>每次</th>
              </tr>
            </thead>
            <tbody>
              {cost.operations.map((row) => (
                <tr key={`${row.operation}-${row.model}`}>
                  <td>
                    <strong>{OPERATIONS[row.operation] ?? row.operation}</strong>
                    <div className="eval-meta">{row.model}</div>
                  </td>
                  <td className="eval-num">{row.calls.toLocaleString()}</td>
                  <td className="eval-num">{row.promptTokens.toLocaleString()}</td>
                  <td className="eval-num">
                    {row.cachedTokens.toLocaleString()}
                    <div className="eval-delta">
                      <span className="eval-up">
                        {row.promptTokens
                          ? `${((row.cachedTokens / row.promptTokens) * 100).toFixed(0)}%`
                          : "—"}
                      </span>
                    </div>
                  </td>
                  <td className="eval-num">{row.completionTokens.toLocaleString()}</td>
                  <td className="eval-num">{ms(row.avgLatencyMs)}</td>
                  <td className="eval-num">¥{row.estimatedCny.toFixed(2)}</td>
                  <td className="eval-num">¥{row.cnyPerCall.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="eval-note">
          命中缓存的输入 token 按更低费率计价，且它<strong>包含在</strong>输入 token 内——
          两者都按全价算会把缓存记成花钱而不是省钱。
        </p>
      </section>

      <section className="eval-section">
        <h2 className="section-title">延迟去了哪里</h2>
        <div className="notice">
          三次外部 API 往返（嵌入 / 重排 / 生成）占 p50 的{" "}
          <strong>{(externalShare * 100).toFixed(1)}%</strong>，本地检索、融合、父块展开合计{" "}
          <strong>{ms(localMs)}</strong>。 直接后果：<strong>想压延迟只能动网络侧</strong>，
          优化本地 SQL 一毫秒也省不下来；反过来，任何「多算几路」的本地实验成本可以忽略。
        </div>
        <div className="table-scroll">
          <table className="table eval-table">
            <thead>
              <tr>
                <th>阶段</th>
                <th>样本</th>
                <th>p50</th>
                <th>占 p50 比例</th>
                <th>位置</th>
              </tr>
            </thead>
            <tbody>
              {latency.stages.map((stage) => (
                <tr key={stage.stage}>
                  <td>
                    <strong>{STAGES[stage.stage] ?? stage.stage}</strong>
                    <div className="eval-meta">{stage.stage}</div>
                  </td>
                  <td className="eval-num">{stage.samples}</td>
                  <td className="eval-num">{ms(stage.p50Ms)}</td>
                  <td className="eval-num">{(stage.shareOfP50 * 100).toFixed(1)}%</td>
                  <td>
                    <span
                      className={`state ${EXTERNAL.has(stage.stage) ? "verdict-mixed" : "verdict-none"}`}
                    >
                      {EXTERNAL.has(stage.stage) ? "外部 API" : "本地"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="eval-note">
          阶段样本数可以少于问答总数：重排在 reranker 不可用时会被跳过并记为降级，
          把缺席当成 0 毫秒平均进去，会报出一次从未发生的提速。
        </p>
      </section>

      {/* The cache is the only component here that can be *wrong* rather than
          merely slow, so its numbers sit next to the rules that bound it. */}
      <section className="eval-section">
        <h2 className="section-title">缓存</h2>
        <div className="stat-row">
          <div className="stat">
            <div className="stat-value">{(cache.hitRate * 100).toFixed(0)}%</div>
            <div className="stat-label">答案命中率</div>
          </div>
          <div className="stat">
            <div className="stat-value">{(cache.embeddingHitRate * 100).toFixed(0)}%</div>
            <div className="stat-label">嵌入命中率</div>
          </div>
          <div className="stat">
            <div className="stat-value">{cache.counts.exact ?? 0}</div>
            <div className="stat-label">精确命中</div>
          </div>
          <div className="stat">
            <div className="stat-value">{cache.counts.semantic ?? 0}</div>
            <div className="stat-label">语义命中</div>
          </div>
          <div className="stat">
            <div className="stat-value">{cache.counts.miss ?? 0}</div>
            <div className="stat-label">未命中</div>
          </div>
          <div className="stat">
            <div className="stat-value">{cache.indexed}</div>
            <div className="stat-label">近邻索引条目</div>
          </div>
        </div>
        <div className="notice">
          <strong>资讯语料不能无脑上语义缓存</strong>（ADR-0017）。三条约束：答案键里含<strong>语料指纹</strong>，且指纹粒度由 planner 的
          `freshness_required` 决定——「最新动态 / 时间线」绑定到精确语料状态，
          其余按天；近邻阈值取 <strong>{cache.threshold}</strong> 而不是常见的 0.85，
          因为「DeepSeek 发布了什么」与「OpenAI 发布了什么」在嵌入空间里很近，
          阈值放松的后果是<strong>自信地回答另一家公司</strong>；
          <strong>拒答永不缓存</strong>，因为它的含义是「语料里还没有」。
          答案 TTL {Math.round(cache.answerTtlSeconds / 60)} 分钟。
        </div>
        {cache.hitRate === 0 && (cache.counts.miss ?? 0) > 0 && (
          <p className="eval-note">
            答案命中率 0% 是<strong>设计结果，不是缓存坏了</strong>：键里含语料指纹，
            而采集每 120 秒写一次，所以时间型问题几乎必然未命中——这正是它该有的行为。
            对照之下嵌入命中率 {(cache.embeddingHitRate * 100).toFixed(0)}% 是真的在省钱：
            嵌入是纯函数，同一段文字永远得到同一个向量，没有新鲜度可言。
          </p>
        )}
      </section>

      {/* The golden set is a fixed sample chosen in advance. This is the
          population, and it is allowed to disagree with it. */}
      <section className="eval-section">
        <h2 className="section-title">线上检索行为</h2>
        <p className="eval-note" style={{ marginTop: 0 }}>
          近 {retrieval.days} 天 {retrieval.queries} 次真实提问、{retrieval.candidates}{" "}
          个候选的聚合。<strong>90 题黄金集回答不了这一节</strong>——那是事先选定的固定样本，
          这里是总体。
        </p>

        <div className="stat-row">
          <div className="stat">
            <div className="stat-value">{retrieval.citedByChannel.dense_only ?? 0}</div>
            <div className="stat-label">仅稠密通道找到</div>
          </div>
          <div className="stat">
            <div className="stat-value">{retrieval.citedByChannel.sparse_only ?? 0}</div>
            <div className="stat-label">仅关键词通道找到</div>
          </div>
          <div className="stat">
            <div className="stat-value">{retrieval.citedByChannel.both ?? 0}</div>
            <div className="stat-label">两个通道都找到</div>
          </div>
          <div className="stat">
            <div className="stat-value">{retrieval.citedFusedRankMedian ?? "—"}</div>
            <div className="stat-label">被引证据融合名次中位数</div>
          </div>
          <div className="stat">
            <div className="stat-value">{retrieval.citedBeyondTop10}</div>
            <div className="stat-label">融合名次在 10 名之后</div>
          </div>
        </div>

        <div className="notice">
          {(retrieval.citedByChannel.sparse_only ?? 0) === 0 ? (
            <>
              <strong>一条不好看的实测结果，照登。</strong> 混合检索的理由一直是那道 NVFP4
              题——正确答案稠密 #14、关键词 #1、融合 #3。那是真的，但它是<strong>一道题</strong>。
              在这 {retrieval.queries} 次真实提问产生的{" "}
              {(retrieval.citedByChannel.dense_only ?? 0) +
                (retrieval.citedByChannel.both ?? 0)}{" "}
              条被引证据里，关键词通道<strong>没有一次</strong>是唯一找到它的那个通道。
              这与 B13 的结论一致：稠密通道一直在兜底。
              轶事不是比率——这一节存在的意义就是把它变成比率，哪怕数字难看。
            </>
          ) : (
            <>
              被引证据中有{" "}
              <strong>{((retrieval.sparseOnlyShare ?? 0) * 100).toFixed(1)}%</strong>{" "}
              只有关键词通道找到。这是混合检索在真实流量上的收益率，而不是一道示例题。
            </>
          )}
        </div>

        <div className="notice">
          <strong>重排确实在干活。</strong> 被引证据的融合名次中位数是{" "}
          <strong>{retrieval.citedFusedRankMedian ?? "—"}</strong>，最深到过第{" "}
          {retrieval.citedFusedRankMax ?? "—"} 名，其中{" "}
          <strong>{retrieval.citedBeyondTop10}</strong> 条融合后排在 10 名之外。
          如果被引的都已经在前三，交叉编码器就不值它占的那 28% 延迟。
        </div>

        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>候选去向</th>
                <th className="eval-num">条数</th>
                <th>含义</th>
              </tr>
            </thead>
            <tbody>
              {retrieval.outcomes.map((row) => (
                <tr key={row.outcome}>
                  <td>
                    <code>{row.outcome}</code>
                  </td>
                  <td className="eval-num">{row.count}</td>
                  <td className="eval-meta">{OUTCOMES[row.outcome] ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="eval-section">
        <h2 className="section-title">语料规模</h2>
        <div className="stat-row">
          <div className="stat">
            <div className="stat-value">{corpus.items.toLocaleString()}</div>
            <div className="stat-label">内容条目</div>
          </div>
          <div className="stat">
            <div className="stat-value">{corpus.chunks.toLocaleString()}</div>
            <div className="stat-label">检索分块</div>
          </div>
          <div className="stat">
            <div className="stat-value">
              {corpus.chunks ? ((corpus.embedded / corpus.chunks) * 100).toFixed(0) : 0}%
            </div>
            <div className="stat-label">已向量化</div>
          </div>
          <div className="stat">
            <div className="stat-value">{corpus.activeSources}</div>
            <div className="stat-label">ACTIVE 信源</div>
          </div>
          <div className="stat">
            <div className="stat-value">{corpus.citations.toLocaleString()}</div>
            <div className="stat-label">已生成引用</div>
          </div>
          <div className="stat">
            <div className="stat-value">{corpus.multiSourceStories}</div>
            <div className="stat-label">多信源事件</div>
          </div>
        </div>
      </section>
    </>
  );
}

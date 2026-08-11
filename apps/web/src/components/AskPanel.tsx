"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { RetrievalTrace } from "@/components/RetrievalTrace";
import { formatDate, formatDateTime } from "@/lib/datetime";

/**
 * The conversation, as one box you keep talking to.
 *
 * This was a search page wearing a chat feature. One answer occupied the page,
 * the next question replaced it, and the transcript existed only in the
 * database — so multi-turn worked end to end and was invisible, which is
 * indistinguishable from not existing. The rebuild inverts what is primary:
 * **`turns` is the page**, an append-only list, and there is no longer a
 * variable holding "the current answer" for the next question to overwrite.
 * The class of bug where submitting a follow-up blanked the screen is gone
 * structurally rather than by being handled.
 *
 * Two things here are not cosmetic. Citations are rendered from the server's
 * resolved list, never from anything the model wrote — a reference the model
 * invented is stripped upstream and cannot appear as a source. And a refusal is
 * shown as a refusal: the locked constraint is that model output is not a
 * trusted fact, so "the retrieved material does not answer this" has to be a
 * visible outcome rather than something padded into a plausible paragraph.
 */

interface Citation {
  number: number;
  itemId: string;
  claim: string;
  title: string;
  sourceName: string;
  url: string;
  publishedAt: string | null;
  sourceTier: string;
  storySlug: string | null;
  independentSources: number;
  /** Cross-encoder score of (claim, cited passage). Null means not scored —
      a reranker outage must not render as "unsupported". */
  supportScore?: number | null;
}

interface Considered {
  itemId: string;
  title: string;
  sourceName: string;
  sourceTier: string;
  publishedAt: string | null;
}

export interface AnswerPayload {
  queryId?: string | null;
  askedAt?: string | null;
  question?: string;
  answerMarkdown: string;
  refused: boolean;
  refusalReason: string | null;
  limitations: string[];
  citations: Citation[];
  considered: Considered[];
  plan?: {
    query_type?: string;
    time_range?: { label?: string; from?: string; to?: string } | null;
  } | null;
  /** Most citations failed the support check. Reported, never a refusal. */
  weakRetrieval?: boolean;
  /** "rag" or "corpus_stats" — the site answering about itself. */
  kind?: string;
  /** The thread this turn belongs to; the server mints it on the first turn. */
  conversationId?: string | null;
  /** What a follow-up was rewritten into, when it was. */
  rewrittenQuestion?: string | null;
  metrics?: {
    total_ms?: number;
    evidence?: number;
    degraded?: string[];
    /** Other names for the same vendor that the question was expanded to. */
    aliases?: string[];
    /** Distinct publishers behind the evidence, after the per-source cap. */
    selection?: { distinct_sources?: number; source_capped?: number };
    support_dropped?: number;
    cache?: { outcome?: string; similarity?: number | null; replayOf?: string };
  };
  /** Only the permalink carries this; the thread list does not fetch it. */
  trace?: TraceRow[];
  /** Client-side only: the progress this turn reported while it ran. Kept on
      the turn rather than in one shared slot, so an earlier answer's trace is
      still its own once the next question has been asked. */
  stages?: StageEvent[];
}

/** One thread in the conversation list. */
interface ThreadSummary {
  conversationId: string;
  title: string;
  turns: number;
  lastAskedAt: string | null;
}

/** One candidate's journey through the funnel. See `rag/trace.py`. */
export interface TraceRow {
  chunkId: string;
  itemId: string | null;
  title: string;
  sourceName: string;
  sourceTier: string;
  denseRank: number | null;
  denseScore: number | null;
  sparseRank: number | null;
  sparseScore: number | null;
  channels: string;
  boosts: string[];
  fusedRank: number | null;
  fusedScore: number | null;
  rerankRank: number | null;
  rerankScore: number | null;
  finalRank: number | null;
  outcome: string;
  excerpt: string;
}

/** What the planner decided, in words a reader can check. */
const QUERY_TYPES: Record<string, string> = {
  recent_updates: "最新动态",
  timeline: "时间线",
  comparison: "对比",
  fact_check: "事实核查",
  explainer: "原理解释",
  abstention: "开放提问",
};

/**
 * Groundedness, shown per citation.
 *
 * `rag_citation.support_score` was defined for this in V001 and was NULL for
 * every row until now: the offline evaluation computed it for 90 golden
 * questions and the live path never did. The reader looking at one answer had
 * no way to tell a well-supported citation from one in the tail.
 *
 * 0.30 is the threshold the evaluation reports against, reused deliberately —
 * a citation the page calls supported must be one the report counted.
 */
const SUPPORT_THRESHOLD = 0.3;

function supportBadge(score: number | null | undefined) {
  // Not scored is not the same as unsupported, and must not look like it.
  if (score === null || score === undefined) return null;
  const supported = score >= SUPPORT_THRESHOLD;
  return (
    <span
      className={`support-badge ${supported ? "support-ok" : "support-weak"}`}
      title={`证据支持度 ${score.toFixed(3)}（交叉编码器对「论断 × 被引段落」打分，阈值 ${SUPPORT_THRESHOLD}）`}
    >
      支持度 {score.toFixed(2)}
    </span>
  );
}

/**
 * A compact, literal account of the evidence behind one answer.
 *
 * This deliberately avoids a single "confidence" score. Citation support,
 * source independence and source tier answer different questions; collapsing
 * them into one percentage would look precise while hiding which part is weak.
 */
function EvidenceSummary({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  const scored = citations.filter((citation) => citation.supportScore != null);
  const supported = scored.filter(
    (citation) => (citation.supportScore ?? 0) >= SUPPORT_THRESHOLD,
  ).length;
  const primary = citations.filter((citation) => citation.sourceTier === "primary").length;
  const publishers = new Set(citations.map((citation) => citation.sourceName)).size;

  return (
    <div className="ask-evidence-summary" aria-label="证据质量概览">
      <span className="ask-evidence-label">证据概览</span>
      <span>{citations.length} 条引用</span>
      <span>{publishers} 家发布方</span>
      {scored.length > 0 && (
        <span>
          支持度通过 {supported}/{scored.length}
        </span>
      )}
      {primary > 0 && <span>{primary} 条一手来源</span>}
    </div>
  );
}

/**
 * Starter questions, each chosen to demonstrate a different property.
 *
 * The page shipped with none, so a first-time visitor faced an empty box with
 * no idea what this corpus can answer — and the refusal example in particular
 * is something nobody would think to try, while being the behaviour that most
 * distinguishes this from a chat box.
 *
 * Tied to the live corpus: the first three are answerable today and the fourth
 * names a model that does not exist. Re-check them when the corpus moves on;
 * an example that has gone stale is worse than no example.
 */
const EXAMPLES: { question: string; shows: string }[] = [
  {
    question: "使用 MXFP4 量化的是哪个模型？",
    shows: "精确型号——纯语义检索会召回成 NVFP4",
  },
  {
    question: "Anthropic 的模型测试引发了几起真实事故？",
    shows: "4 家独立信源佐证同一事件",
  },
  {
    question: "最近一周 llama.cpp 修复了哪些问题？",
    shows: "「最近一周」被解析成绝对时间区间",
  },
  {
    question: "Qwen4-Ultra 的参数量是多少？",
    shows: "语料里没有 → 拒答而不是编造",
  },
];

const TIERS: Record<string, { label: string; className: string }> = {
  primary: { label: "一手", className: "tier-primary" },
  secondary: { label: "媒体", className: "tier-secondary" },
  expert: { label: "专家", className: "tier-expert" },
  community: { label: "社区", className: "tier-community" },
};

/**
 * The nine pipeline stages collapsed into the four a reader can act on.
 *
 * `dense`, `sparse` and `fuse` cost 67ms between them and finish before the
 * eye can register them; listing each would be a progress bar that lies about
 * where the time goes. The three that dominate — embed, rerank, generate — get
 * their own line, because those are the seconds someone is actually waiting.
 */
const STEPS = [
  { key: "plan", label: "理解问题" },
  { key: "embed", label: "检索证据" },
  { key: "rerank", label: "重排候选" },
  { key: "generate", label: "生成回答" },
] as const;

interface StageEvent {
  stage: string;
  ms?: number;
  found?: number;
  evidence?: number;
  time_range?: string | null;
  /** `cache` only: which layer answered. */
  outcome?: string;
  similarity?: number;
  /** `generate` reports when it begins, because it is the one stage whose end
      coincides with the answer. Every other stage reports on completion. */
  started?: boolean;
}

/**
 * Render `[1]` inside the answer as a control that reaches its source.
 *
 * Until now the markers were plain text in a paragraph. The entire claim this
 * feature makes — every fact carries a source you can check — was therefore
 * something the reader had to take on trust and match up by eye. The server
 * already guarantees each number resolves to a real passage (`bind_citations`
 * strips the ones that do not), so the only missing piece was making that
 * guarantee reachable.
 */
function renderWithCitations(
  line: string,
  citations: Citation[],
  onFocus: (n: number) => void,
  active: number | null,
) {
  const byNumber = new Map(citations.map((c) => [c.number, c]));

  // `**bold**` as well as `[n]`. The prompt asks for markdown and the model
  // obliges, so without this the reader sees literal asterisks around the one
  // word the answer was emphasising — "确认共引发 **三起** 真实事件".
  return line.split(/(\[\d+\]|\*\*[^*]+\*\*)/g).map((part, index) => {
    const bold = /^\*\*([^*]+)\*\*$/.exec(part);
    if (bold) return <strong key={index}>{bold[1]}</strong>;

    const match = /^\[(\d+)\]$/.exec(part);
    if (!match) return <span key={index}>{part}</span>;

    const number = Number(match[1]);
    const citation = byNumber.get(number);
    // A marker with no matching citation should not have survived the server's
    // binding. If one does, show it as text rather than a dead control.
    if (!citation) return <span key={index}>{part}</span>;

    return (
      <button
        key={index}
        type="button"
        className={`cite-ref${active === number ? " is-active" : ""}`}
        onClick={() => onFocus(number)}
        title={`${citation.title} · ${citation.sourceName}`}
        aria-label={`查看来源 ${number}：${citation.title}`}
      >
        {number}
      </button>
    );
  });
}

/**
 * The answer body, as blocks rather than as one paragraph per line.
 *
 * Every line used to become a `<p>`, so a markdown list rendered as a column of
 * identical paragraphs each starting with a stray hyphen — eleven of them, with
 * nothing marking which was the answer. The prompt now requires a lead
 * paragraph before any list (`rag-answer-v2`); this is the half that makes that
 * structure visible instead of flattening it back out.
 */
function renderAnswerBody(
  markdown: string,
  citations: Citation[],
  onFocus: (n: number) => void,
  active: number | null,
) {
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];

  const flush = () => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="ask-points">
        {items.map((item, index) => (
          <li key={index}>{renderWithCitations(item, citations, onFocus, active)}</li>
        ))}
      </ul>,
    );
  };

  for (const raw of markdown.split("\n")) {
    const line = raw.trim();
    if (!line) {
      flush();
      continue;
    }

    const bullet = /^[-*·]\s+(.*)$/.exec(line);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }

    flush();
    // The first prose block is the conclusion the prompt asks for. Marking it
    // is the whole point: a reader who stops after one paragraph should have
    // the answer.
    const isLead = blocks.length === 0;
    blocks.push(
      <p key={`p-${blocks.length}`} className={isLead ? "ask-lead" : undefined}>
        {renderWithCitations(line, citations, onFocus, active)}
      </p>,
    );
  }
  flush();
  return blocks;
}

/** The four-step progress list, from the stage events one turn reported. */
function Progress({ stages, open }: { stages: StageEvent[]; open: boolean }) {
  // A stage that has only *started* is not done. `generate` is the whole point
  // of the distinction: it reports at its beginning and takes 5.7s at p50, so
  // treating any reported stage as complete drew four ticks and then left the
  // reader watching a finished checklist for six seconds.
  const done = new Set(stages.filter((s) => !s.started).map((s) => s.stage));
  const running = stages.filter((s) => s.started).map((s) => s.stage);
  const cacheHit = stages.find((s) => s.stage === "cache" && s.outcome !== "miss");
  const found = stages.find((s) => s.stage === "fuse")?.found;
  const evidence = stages.find((s) => s.stage === "select")?.evidence;

  // A cache hit runs no pipeline, so the four-step list has nothing to report
  // and rendered as an empty box. Saying which layer answered is both more
  // honest and more useful — a reader who sees a stale-looking answer should be
  // able to tell it came from cache.
  if (cacheHit) {
    return (
      <div className="ask-trace ask-cache-hit">
        <strong>命中缓存</strong>
        {cacheHit.outcome === "semantic" ? (
          <span className="ask-step-detail">语义近邻 · 相似度 {cacheHit.similarity?.toFixed(4)}</span>
        ) : (
          <span className="ask-step-detail">同一问题、同一份语料</span>
        )}
        <span className="ask-step-detail">未调用模型</span>
      </div>
    );
  }

  return (
    <details className="ask-trace" open={open} aria-live="polite">
      <summary className="ask-trace-summary">
        检索过程
        {found ? <span className="ask-step-detail">{found} 条候选</span> : null}
        {evidence ? <span className="ask-step-detail">{evidence} 段证据</span> : null}
      </summary>
      <ol className="ask-progress">
        {STEPS.map((step) => {
          const isDone = done.has(step.key);
          // Active either because the server said this stage began, or because
          // it is the first stage not yet reported — the fast ones send no
          // "started" event, and inventing one would mean guessing at a
          // duration the server already knows.
          const active =
            !isDone &&
            (running.includes(step.key) ||
              STEPS.filter((s) => done.has(s.key)).length === STEPS.indexOf(step));
          return (
            <li
              key={step.key}
              className={`ask-step${isDone ? " is-done" : ""}${active ? " is-active" : ""}`}
            >
              <span className="ask-step-mark" aria-hidden="true">
                {isDone ? "✓" : active ? "•" : ""}
              </span>
              <span>{step.label}</span>
              {step.key === "embed" && found ? (
                <span className="ask-step-detail">{found} 条候选</span>
              ) : null}
              {step.key === "rerank" && evidence ? (
                <span className="ask-step-detail">选出 {evidence} 条证据</span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </details>
  );
}

/**
 * One completed exchange: what was asked, and what came back with it.
 *
 * Its own component with its own citation-focus state, because there are now
 * several on screen at once. A single shared `activeCite` would highlight
 * source 3 in every answer that has one; the ids are scoped by turn for the
 * same reason.
 */
function ChatTurn({
  turn,
  index,
  isLatest,
  children,
}: {
  turn: AnswerPayload;
  index: number;
  isLatest: boolean;
  /** The editable time window, on the newest turn only — re-asking is about
      what to do next, not about editing something already answered. */
  children?: React.ReactNode;
}) {
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const key = turn.queryId ?? `t${index}`;

  const focusCitation = (number: number) => {
    setActiveCite(number);
    document
      .getElementById(`cite-${key}-${number}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <article className={`chat-turn${isLatest ? " is-latest" : ""}`}>
      <div className="chat-ask">
        <span className="chat-avatar" aria-hidden="true">
          你
        </span>
        <div className="chat-bubble">
          {turn.question}
          {turn.askedAt && <time className="chat-time">{formatDate(turn.askedAt)}</time>}
        </div>
      </div>

      <div className="chat-reply">
        <span className="chat-avatar is-ai" aria-hidden="true">
          AI
        </span>
        <div className="ask-answer">
          {/* A follow-up that was understood as something else. Shown for the
              same reason the resolved time window is: a reader whose 「它呢」 was
              tied to the wrong antecedent can see it rather than conclude the
              system is broken. */}
          {turn.rewrittenQuestion && (
            <p className="ask-rewrite" role="status">
              这是一个追问，已理解为：<strong>{turn.rewrittenQuestion}</strong>
            </p>
          )}

          {/* What the planner decided, before any of it was used. The absolute
              window matters most: "最近" became a real interval, and if it
              caught the wrong one the reader can see that rather than guess. */}
          {turn.plan && (turn.plan.query_type || turn.plan.time_range) && (
            <div className="ask-plan">
              {turn.plan.query_type && (
                <span className="ask-plan-chip">
                  {QUERY_TYPES[turn.plan.query_type] ?? turn.plan.query_type}
                </span>
              )}
              {turn.plan.time_range?.from && turn.plan.time_range?.to ? (
                <span className="ask-plan-chip">
                  {turn.plan.time_range.label ?? "时间范围"}
                  <span className="ask-plan-range">
                    {formatDate(turn.plan.time_range.from)} – {formatDate(turn.plan.time_range.to)}
                  </span>
                </span>
              ) : (
                <span className="ask-plan-chip">全部时间</span>
              )}
              {children}
              {turn.metrics?.evidence != null && (
                <span className="ask-plan-chip">{turn.metrics.evidence} 段证据</span>
              )}
              {/* How the question was read, not just what it asked. 「智谱」 also
                  searching for GLM is the difference between an answer and a
                  wrong "nothing was released"; showing it lets the reader tell
                  a good expansion from a wrong one. */}
              {turn.metrics?.aliases && turn.metrics.aliases.length > 0 && (
                <span className="ask-plan-chip ask-plan-alias">
                  同时检索
                  <span className="ask-plan-range">
                    {turn.metrics.aliases.slice(0, 4).join(" · ")}
                  </span>
                </span>
              )}
              {/* One publisher is not corroboration however many documents it
                  quotes, and the count was previously buried in the footer. */}
              {turn.metrics?.selection?.distinct_sources != null && (
                <span className="ask-plan-chip">
                  {turn.metrics.selection.distinct_sources} 家信源
                </span>
              )}
              {turn.askedAt && (
                <span className="ask-plan-chip" title="回答只依据这一时刻之前已进入语料库的内容">
                  检索截至
                  <span className="ask-plan-range">{formatDateTime(turn.askedAt)}</span>
                </span>
              )}
            </div>
          )}

          {/* The site answering about itself. Marked rather than blended in: it
              has no citations by construction, and a reader who has been told
              every fact carries a source should be able to see why this one
              does not instead of assuming they were lost. */}
          {turn.kind === "corpus_stats" && (
            <p className="ask-kind" role="status">
              这是<strong>本站运行数据</strong>，直接来自数据库计数，不是检索结果，因此没有引用来源。
            </p>
          )}

          {/* Most of this answer's citations failed the support check. The
              signal existed and was spent on a line of small print identical to
              every other note — while the answer it belonged to stated that
              智谱 had released nothing, over a window holding three Zhipu items. */}
          {!turn.refused && turn.weakRetrieval && (
            <p className="ask-weak" role="status">
              这次检索的证据大多没通过支持度校验
              {turn.metrics?.support_dropped
                ? `（移除了 ${turn.metrics.support_dropped} 条引用）`
                : null}
              ，下面的结论可信度偏低，建议换个说法再问一次或放宽时间范围。
            </p>
          )}

          {turn.refused ? (
            <div className="ask-refusal">
              <strong>没有足够证据回答这个问题。</strong>
              <p>{turn.refusalReason ?? "检索到的内容不足以支持一个可核实的回答。"}</p>
              <p className="ask-refusal-note">
                这是刻意的：本站不会用模型的常识补答，没有来源支撑的内容不会显示。
              </p>

              {/* A refusal used to end here. The system knows exactly what it
                  read; showing it turns a dead end into something the reader
                  can act on — usually by noticing the window is wrong. */}
              {turn.considered?.length > 0 && (
                <div className="ask-considered">
                  <p className="ask-considered-title">检索到但不足以支撑回答的内容：</p>
                  <ul>
                    {turn.considered.slice(0, 5).map((row) => (
                      <li key={row.itemId}>
                        <a href={`/items/${row.itemId}`}>{row.title}</a>
                        <span className="ask-source-meta">
                          {row.sourceName}
                          {row.publishedAt && ` · ${formatDate(row.publishedAt)}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <div className="ask-body">
              {renderAnswerBody(turn.answerMarkdown, turn.citations, focusCitation, activeCite)}
            </div>
          )}

          {!turn.refused && <EvidenceSummary citations={turn.citations} />}

          {turn.limitations.length > 0 && (
            <ul className="ask-limitations">
              {turn.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          )}

          {turn.citations.length > 0 && (
            <details className="ask-sources">
              <summary className="ask-sources-title">
                引用来源
                <span className="ask-sources-count">{turn.citations.length} 条</span>
              </summary>
              <ol className="ask-source-list">
                {turn.citations.map((citation) => {
                  const tier = TIERS[citation.sourceTier];
                  return (
                    <li
                      key={citation.number}
                      id={`cite-${key}-${citation.number}`}
                      className={`ask-source${activeCite === citation.number ? " is-active" : ""}`}
                    >
                      <span className="ask-source-no">[{citation.number}]</span>
                      <div>
                        <div className="ask-source-head">
                          {/* Internal first: the detail page carries the Chinese
                              summary, entities and the event timeline. The
                              publisher's own copy is one click further, never
                              replaced. */}
                          <a href={`/items/${citation.itemId}`}>{citation.title}</a>
                          {tier && (
                            <span className={`tier-badge ${tier.className}`}>{tier.label}</span>
                          )}
                          {/* M3's whole purpose, finally visible where it
                              changes a reader's mind: this is not one outlet's
                              word. */}
                          {citation.independentSources > 1 && (
                            <a
                              className="corroboration-badge"
                              href={
                                citation.storySlug ? `/stories/${citation.storySlug}` : "/stories"
                              }
                            >
                              {citation.independentSources} 家独立信源
                            </a>
                          )}
                          {supportBadge(citation.supportScore)}
                        </div>
                        <div className="ask-source-meta">
                          {citation.sourceName}
                          {citation.publishedAt && ` · ${formatDate(citation.publishedAt)}`}
                          {" · "}
                          <a href={citation.url} target="_blank" rel="noopener noreferrer">
                            阅读原文 ↗
                          </a>
                        </div>
                        {citation.claim && (
                          <div className="ask-source-claim">支撑：{citation.claim}</div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </details>
          )}

          {/* The progress this turn reported, kept with it and collapsed. It
              used to be removed the moment the answer landed, which threw away
              the one artefact showing *how* the answer was reached — the thing
              that distinguishes this from a chat box. */}
          {turn.stages && turn.stages.length > 0 && <Progress stages={turn.stages} open={false} />}

          <p className="ask-meta">
            {turn.metrics?.total_ms && `耗时 ${(turn.metrics.total_ms / 1000).toFixed(1)}s`}
            {turn.citations.length > 0 &&
              ` · ${new Set(turn.citations.map((c) => c.sourceName)).size} 个信源`}
            {turn.metrics?.degraded?.length ? ` · 降级：${turn.metrics.degraded.join(", ")}` : ""}
            {/* Addressable. The id has always been returned with the answer;
                until there was a route that read it back it pointed nowhere. */}
            {turn.queryId && (
              <>
                {" · "}
                <a className="ask-permalink" href={`/ask/${turn.queryId}`}>
                  永久链接
                </a>
              </>
            )}
          </p>

          {turn.trace && turn.trace.length > 0 && <RetrievalTrace rows={turn.trace} />}
        </div>
      </div>
    </article>
  );
}

/**
 * @param initial A stored turn to open with. The permalink page passes the row
 * it rendered on the server, so the shared link and the live conversation are
 * the same component rather than two renderers that can drift apart — and
 * because that row now carries its `conversationId`, a shared answer is
 * somewhere a reader can keep asking from rather than a dead end.
 */
export function AskPanel({ initial }: { initial?: AnswerPayload } = {}) {
  const [question, setQuestion] = useState("");
  // The transcript, and the only thing that decides what is on screen. There is
  // deliberately no "current answer" variable: that one was what the next
  // question overwrote, and clearing it to show progress is what emptied the
  // page mid-conversation.
  const [turns, setTurns] = useState<AnswerPayload[]>(initial ? [initial] : []);
  // The question being answered right now, appended after the transcript rather
  // than replacing any of it.
  const [pending, setPending] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stages, setStages] = useState<StageEvent[]>([]);
  // The answer as it is written. Everything here has already been resolved
  // server-side — invented citation numbers are gone and the real ones carry
  // their final number — and nothing arrives until the answer is guaranteed not
  // to become a refusal, so none of it is ever taken back.
  const [streamed, setStreamed] = useState("");
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  // The range the reader set, if they corrected the planner's. Held here rather
  // than derived from the answer: it has to survive the re-ask that applies it,
  // and the answer it produces reports the new range, not the old.
  const [readerWindow, setReaderWindow] = useState<{ from: string; to: string } | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(
    initial?.conversationId ?? null,
  );
  // Follow-ups this answer's own sources could support. Fetched after it
  // renders, so the answer is never slower for them.
  const [suggestions, setSuggestions] = useState<string[]>([]);

  // The conversation list, open only while the reader is choosing from it. It
  // is a drawer, not a panel: leaving it open under the box would put a stack
  // of other conversations between the answer and the next question.
  const [historyOpen, setHistoryOpen] = useState(false);

  const bottom = useRef<HTMLDivElement | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const loadThreads = useCallback(() => {
    fetch("/api/ask?threads=1")
      .then((r) => r.json())
      .then((body) => setThreads((body.threads ?? []) as ThreadSummary[]))
      .catch(() => {
        /* the conversation list is an enhancement; asking works without it */
      });
  }, []);

  // Restore the thread this browser was in the middle of. Without it a reload
  // dropped the conversation and left the reader looking at the site's shared
  // history instead of their own — the two were being served by one route.
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = sessionStorage.getItem("ahr:conversation");
    } catch {
      stored = null;
    }
    if (!stored || initial) return;

    let cancelled = false;
    fetch(`/api/ask?conversation=${encodeURIComponent(stored)}`)
      .then((response) => response.json())
      .then((data) => {
        const restored: AnswerPayload[] = data.turns ?? [];
        if (cancelled || restored.length === 0) return;
        setTurns(restored);
        setConversationId(stored);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [initial]);

  useEffect(loadThreads, [loadThreads]);

  // Follow the conversation down as it grows. Only on submit: scrolling when
  // the answer lands would move the page under a reader already reading the
  // streamed copy of the same text.
  useEffect(() => {
    if (pending) bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [pending]);

  function startFresh() {
    setConversationId(null);
    try {
      sessionStorage.removeItem("ahr:conversation");
    } catch {
      // Nothing to clean up if it was never stored.
    }
    setTurns([]);
    setPending(null);
    setStreamed("");
    setStages([]);
    setSuggestions([]);
    setError(null);
    setReaderWindow(null);
    setQuestion("");
    inputRef.current?.focus();
  }

  /** Reopen a stored thread and keep asking inside it. */
  async function resume(id: string) {
    if (loading) return;
    try {
      const response = await fetch(`/api/ask?conversation=${encodeURIComponent(id)}`);
      const data = await response.json();
      const restored: AnswerPayload[] = data.turns ?? [];
      if (restored.length === 0) return;
      setTurns(restored);
      setConversationId(id);
      setSuggestions([]);
      setError(null);
      // The list has done its job. Leaving it open would keep a stack of other
      // conversations under the one just opened, which is the shape the reader
      // was looking at when they said the page was a pile of records.
      setHistoryOpen(false);
      try {
        sessionStorage.setItem("ahr:conversation", id);
      } catch {
        // Private mode or a full quota; the thread still works for this page.
      }
      // To the top of the conversation, not the bottom: a thread being reopened
      // is one to read from the beginning.
      box.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      inputRef.current?.focus();
    } catch {
      setError("这段对话没能打开，请重试");
    }
  }

  async function ask(text: string, window?: { from: string; to: string } | null) {
    const trimmed = text.trim();
    if (trimmed.length < 2 || loading) return;

    setLoading(true);
    setError(null);
    setPending(trimmed);
    setQuestion("");
    setSuggestions([]);
    setStages([]);
    setStreamed("");

    try {
      const response = await fetch("/api/ask?stream=1", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          question: trimmed,
          ...(conversationId ? { conversationId } : {}),
          ...(window ? { timeFrom: window.from, timeTo: window.to } : {}),
        }),
      });

      if (!response.ok || !response.body) {
        const body = await response.json().catch(() => ({}));
        setError(String(body.error ?? "回答失败"));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let seen: StageEvent[] = [];

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line. A frame can arrive split
        // across reads, so only whole ones are consumed and the remainder is
        // carried forward.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          const event = /^event: (.+)$/m.exec(frame)?.[1];
          const data = /^data: (.+)$/m.exec(frame)?.[1];
          if (!event || !data) continue;

          const payload = JSON.parse(data);
          if (event === "stage") {
            seen = [...seen, payload as StageEvent];
            setStages(seen);
          } else if (event === "delta") {
            setStreamed((prior) => prior + String(payload.text ?? ""));
          } else if (event === "answer") {
            // The progress rides along on the turn, so this answer keeps its
            // own trace once the next question has been asked.
            const landed = { ...(payload as AnswerPayload), stages: seen };
            // The thread the next question continues. The server mints it on
            // the first turn, so the client never invents an id that would then
            // have to be trusted.
            if (landed.conversationId) {
              setConversationId(landed.conversationId);
              // Survives a reload. `sessionStorage`, not `localStorage`: this is
              // one sitting, and a thread resumed a week later would carry
              // context the reader has forgotten into a corpus that has moved.
              try {
                sessionStorage.setItem("ahr:conversation", landed.conversationId);
              } catch {
                // Private mode or a full quota. The conversation still works for
                // this page; only resuming after a reload is lost.
              }
            }
            if (landed.queryId) {
              fetch(`/api/ask?suggestions=${encodeURIComponent(landed.queryId)}`)
                .then((response) => response.json())
                .then((data) => setSuggestions(data.suggestions ?? []))
                .catch(() => setSuggestions([]));
            }
            // Append. Nothing is replaced, which is the whole design: there is
            // no slot for the previous answer to be evicted from.
            setTurns((prior) => [...prior, landed]);
            setPending(null);
            // The verified answer replaces the streamed copy. They are the same
            // text by construction — the tests pin that — so this swaps in the
            // version that also carries the citations the markers link to.
            setStreamed("");
            setReaderWindow(null);
          } else if (event === "error") {
            setError(String(payload.error ?? "回答失败"));
          }
        }
      }
    } catch {
      setError("网络错误，请重试");
    } finally {
      setLoading(false);
      setPending(null);
      loadThreads();
    }
  }

  const latest = turns.length > 0 ? turns[turns.length - 1] : null;
  const empty = turns.length === 0 && !pending && !error;
  // Threads other than the open one. The open one is rendered in full above;
  // listing it again would offer the reader a link to where they already are.
  const otherThreads = threads.filter((t) => t.conversationId !== conversationId);

  return (
    <>
      <div className="chat" ref={box}>
        {/* Which conversation this is, and the way out of it. 换个新话题 used to
            live in the note under the composer — a line of explanatory text is
            not where a control goes, and the reader looking for "new chat"
            found nothing. */}
        <div className="chat-head">
          <div className="chat-head-what">
            {conversationId && turns.length > 0 ? (
              <>
                <span className="ask-session-dot" aria-hidden="true" />
                <span className="chat-head-topic" title={turns[0].question}>
                  {turns[0].question}
                </span>
                <span className="chat-head-count">{turns.length} 轮</span>
              </>
            ) : (
              <span className="chat-head-fresh">新对话</span>
            )}
          </div>
          <button
            type="button"
            className="chat-new"
            onClick={startFresh}
            // Disabled on an empty box rather than hidden: a control that
            // disappears when it has nothing to do is one the reader cannot
            // find when it does.
            disabled={turns.length === 0 && !pending}
          >
            ＋ 新建对话
          </button>
        </div>

        <div className="chat-log">
          {empty && (
            <div className="chat-empty">
              <span className="chat-empty-kicker">基于站内原始资讯</span>
              <h2 className="chat-empty-title">从一个具体问题开始</h2>
              <p className="chat-empty-lead">
                可询问近期模型发布、公司动态或产品变化；回答后还能直接追问
                <strong>「它」「那家公司」</strong>。
              </p>
              <ul className="chat-trust" aria-label="问答能力边界">
                <li>原文引用</li>
                <li>时间范围可修正</li>
                <li>证据不足会拒答</li>
              </ul>
              <div className="ask-examples" role="group" aria-label="示例问题">
                <span className="ask-examples-label">试试这样问</span>
                {EXAMPLES.map((example) => (
                  <button
                    key={example.question}
                    type="button"
                    className="ask-example"
                    title={example.shows}
                    onClick={() => void ask(example.question)}
                  >
                    {example.question}
                    <span className="ask-example-shows">{example.shows}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, index) => (
            <ChatTurn
              key={turn.queryId ?? index}
              turn={turn}
              index={index}
              isLatest={index === turns.length - 1}
            >
              {/* Displaying the resolved window was half the promise. A reader
                  who sees the wrong week should be able to fix it rather than
                  conclude the system is broken; until now fixing it meant
                  retyping the question and hoping. Newest turn only: re-asking
                  is about what to do next. */}
              {index === turns.length - 1 && !pending && (
                <details className="ask-window">
                  <summary className="ask-window-toggle">改时间范围</summary>
                  <div className="ask-window-body">
                    <label>
                      从
                      <input
                        type="date"
                        value={readerWindow?.from ?? (turn.plan?.time_range?.from ?? "").slice(0, 10)}
                        onChange={(event) =>
                          setReaderWindow((prev) => ({
                            from: event.target.value,
                            to: prev?.to ?? (turn.plan?.time_range?.to ?? "").slice(0, 10),
                          }))
                        }
                      />
                    </label>
                    <label>
                      到
                      <input
                        type="date"
                        value={readerWindow?.to ?? (turn.plan?.time_range?.to ?? "").slice(0, 10)}
                        onChange={(event) =>
                          setReaderWindow((prev) => ({
                            from: prev?.from ?? (turn.plan?.time_range?.from ?? "").slice(0, 10),
                            to: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="ask-window-apply"
                      disabled={loading || !readerWindow?.from || !readerWindow?.to}
                      onClick={() => {
                        if (readerWindow?.from && readerWindow?.to) {
                          void ask(turn.question ?? "", readerWindow);
                        }
                      }}
                    >
                      用这个范围重问
                    </button>
                  </div>
                </details>
              )}
            </ChatTurn>
          ))}

          {/* The turn in flight. An extra entry at the end of the transcript,
              never a replacement for it — the previous answer stays exactly
              where the reader left it while this one is written. */}
          {pending && (
            <article className="chat-turn is-pending">
              <div className="chat-ask">
                <span className="chat-avatar" aria-hidden="true">
                  你
                </span>
                <div className="chat-bubble">{pending}</div>
              </div>
              <div className="chat-reply">
                <span className="chat-avatar is-ai" aria-hidden="true">
                  AI
                </span>
                <div className="ask-answer" aria-busy="true">
                  {stages.length > 0 && <Progress stages={stages} open />}
                  {/* `.ask-draft`, deliberately *not* `.ask-body`: a partial
                      answer and a verified one must not look the same to
                      anything reading the DOM. Reusing the class made "the
                      answer has landed" indistinguishable from "the first
                      sentence has landed", and three browser tests that had
                      waited on `.ask-body` started asserting against a page
                      whose sources had not been delivered yet. */}
                  {streamed && (
                    <div className="ask-draft">{renderAnswerBody(streamed, [], () => {}, null)}</div>
                  )}
                  <p className="ask-meta ask-streaming" aria-live="polite">
                    {streamed ? "正在生成…" : "正在检索证据…"}
                  </p>
                </div>
              </div>
            </article>
          )}

          {error && (
            <div className="ask-answer chat-error" role="alert">
              <p className="filter-note">{error}</p>
            </div>
          )}

          <div ref={bottom} />
        </div>

        {/* The composer, pinned to the bottom of the box. It stays reachable
            however long the transcript grows, which is what makes this one
            conversation rather than a page you re-submit. */}
        <div className="chat-composer">
          {/* The invitation multi-turn was missing. Clicking asks in the same
              thread, so 「它呢」 keeps working from here — the suggestion and the
              conversation are the same feature seen from two ends. */}
          {suggestions.length > 0 && !loading && (
            <div className="ask-followups">
              <span className="ask-followups-label">接着问：</span>
              {suggestions.map((text) => (
                <button
                  key={text}
                  type="button"
                  className="ask-followup"
                  onClick={() => void ask(text)}
                >
                  {text}
                </button>
              ))}
            </div>
          )}

          <form
            className="ask-form"
            onSubmit={(event) => {
              event.preventDefault();
              void ask(question);
            }}
          >
            <input
              ref={inputRef}
              className="ask-input"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={
                conversationId
                  ? "接着问，会带上上文（可以用「它」指代上一个话题）…"
                  : "问一个关于最近 AI 动态的问题…"
              }
              maxLength={300}
              aria-label="问题"
            />
            <button className="button ask-submit" type="submit" disabled={loading}>
              {loading ? "检索中…" : "提问"}
            </button>
          </form>

          {/* One sentence, and no control in it. The header owns starting over;
              repeating it here was two buttons for one action. */}
          <div className="chat-status">
            {conversationId && turns.length > 0 ? (
              <span>下一个问题会带上以上 {turns.length} 轮的上下文，可以直接用「它」指代。</span>
            ) : (
              <span>回答只依据站内已采集的资讯，每条事实都标注来源，证据不足时会拒答。</span>
            )}
          </div>
        </div>
      </div>

      {/* Earlier conversations, one row per thread. Clicking reopens the whole
          thread in the box above and keeps asking inside it — the resumable
          unit is the conversation, not one line of it. */}
      {otherThreads.length > 0 && (
        <details
          className="ask-history"
          open={historyOpen}
          onToggle={(event) => setHistoryOpen(event.currentTarget.open)}
        >
          <summary className="ask-history-title">
            历史对话
            <span className="ask-history-count">{otherThreads.length} 段</span>
            <span className="ask-history-note">
              暂无账号体系，这里是本站的公共记录（M5 加鉴权后按人区分）
            </span>
          </summary>

          <ul className="ask-history-list">
            {otherThreads.map((row) => (
              <li key={row.conversationId} className="ask-history-row">
                <button
                  type="button"
                  className="ask-history-head"
                  onClick={() => void resume(row.conversationId)}
                  disabled={loading}
                >
                  <span className="ask-history-q">{row.title}</span>
                  <span className="ask-history-meta">
                    {row.turns} 轮
                    {row.lastAskedAt && ` · ${formatDate(row.lastAskedAt)}`}
                    <span className="ask-history-resume">继续这段对话 →</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* Rendered here rather than in the page so it sits below the box it
          describes, and only once there is nothing more useful to say. */}
      {latest === null && !pending && (
        <div className="notice">
          检索走的是<strong>混合召回 + 交叉编码器重排</strong>：稠密向量负责语义，
          关键词通道负责精确型号与版本号（纯语义检索会把 MXFP4 召回成 NVFP4），
          时间词解析成绝对区间后作为过滤条件。
          引用编号由服务端反查真实段落生成，<strong>模型自己写的来源不会被显示</strong>。
        </div>
      )}
    </>
  );
}

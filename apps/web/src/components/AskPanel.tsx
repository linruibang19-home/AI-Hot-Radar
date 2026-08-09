"use client";

import { useEffect, useState } from "react";

import { RetrievalTrace } from "@/components/RetrievalTrace";
import { formatDate } from "@/lib/datetime";

/**
 * The question box and its answer.
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
  };
  /** Only the permalink carries this; the history list does not fetch it. */
  trace?: TraceRow[];
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
 * Source tiers, shown as a badge on every citation.
 *
 * This is the tier that already drives the §6 ranking boost and the selection
 * algorithm — the reader deciding whether to believe a claim deserves the same
 * information the ranker used.
 */
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

/**
 * @param initial A stored conversation to show on load. The permalink page
 * passes the row it rendered on the server, so the shared link and the live ask
 * box are the same component rather than two renderers that can drift apart.
 */
export function AskPanel({ initial }: { initial?: AnswerPayload } = {}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AnswerPayload | null>(initial ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stages, setStages] = useState<StageEvent[]>([]);
  // The answer as it is written. Everything here has already been resolved
  // server-side — invented citation numbers are gone and the real ones carry
  // their final number — and nothing arrives until the answer is guaranteed not
  // to become a refusal, so none of it is ever taken back.
  const [streamed, setStreamed] = useState("");
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const [history, setHistory] = useState<AnswerPayload[]>([]);
  const [openHistory, setOpenHistory] = useState<string | null>(null);
  // The range the reader set, if they corrected the planner's. Held here
  // rather than derived from the answer: it has to survive the re-ask that
  // applies it, and the answer it produces reports the new range, not the old.
  const [readerWindow, setReaderWindow] = useState<{ from: string; to: string } | null>(null);
  // The thread. Held here rather than derived from `answer`, because it has to
  // survive the answer being replaced by the next turn — that is the whole
  // point of it.
  const [conversationId, setConversationId] = useState<string | null>(
    initial?.conversationId ?? null,
  );
  // Earlier turns of this thread, oldest first. The server already stores them;
  // this is only what the reader can see without a round trip.
  const [thread, setThread] = useState<AnswerPayload[]>(initial ? [initial] : []);

  // Conversations live in `rag_query`, written in the same transaction as the
  // answer. Loading them on mount is what makes a conversation survive
  // navigating to a source and coming back — previously the answer existed only
  // in this component's state and one click destroyed it.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/ask")
      .then((r) => r.json())
      .then((body) => {
        if (!cancelled) setHistory((body.conversations ?? []) as AnswerPayload[]);
      })
      .catch(() => {
        /* history is an enhancement; the ask box works without it */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function focusCitation(number: number) {
    setActiveCite(number);
    document
      .getElementById(`cite-${number}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function ask(text: string, window?: { from: string; to: string } | null) {
    const trimmed = text.trim();
    if (trimmed.length < 2 || loading) return;

    setLoading(true);
    setError(null);
    setAnswer(null);
    setStages([]);
    setStreamed("");
    setActiveCite(null);

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
            setStages((prior) => [...prior, payload as StageEvent]);
          } else if (event === "delta") {
            setStreamed((prior) => prior + String(payload.text ?? ""));
          } else if (event === "answer") {
            const landed = payload as AnswerPayload;
            setAnswer(landed);
            // The thread the next question continues. The server mints it on
            // the first turn, so the client never invents an id that would then
            // have to be trusted.
            if (landed.conversationId) setConversationId(landed.conversationId);
            setThread((prior) => [...prior, landed]);
            // The verified answer replaces the streamed copy. They are the same
            // text by construction — the tests pin that — so this swaps in the
            // version that also carries the citations the markers link to.
            setStreamed("");
            // Prepend rather than refetch: the row is already committed, and a
            // round trip would show the reader their own answer arriving twice.
            setHistory((prior) => [
              landed,
              ...prior.filter((row) => row.queryId !== landed.queryId),
            ]);
          } else if (event === "error") {
            setError(String(payload.error ?? "回答失败"));
          }
        }
      }
    } catch {
      setError("网络错误，请重试");
    } finally {
      setLoading(false);
    }
  }

  // A stage that has only *started* is not done. `generate` is the whole point
  // of the distinction: it reports at its beginning and takes 5.7s at p50, so
  // treating any reported stage as complete drew four ticks and then left the
  // reader watching a finished checklist for six seconds.
  const done = new Set(stages.filter((s) => !s.started).map((s) => s.stage));
  const running = stages.filter((s) => s.started).map((s) => s.stage);
  const cacheHit = stages.find((s) => s.stage === "cache" && s.outcome !== "miss");
  const found = stages.find((s) => s.stage === "fuse")?.found;
  const evidence = stages.find((s) => s.stage === "select")?.evidence;

  // The answer on screen is already rendered in full above; repeating it in the
  // history list would show the same thing twice.
  const past = history.filter((row) => !answer || row.queryId !== answer.queryId);

  // On a permalink the answer already *is* the page, so offering a link to it
  // would be a control that goes nowhere.
  const isPermalink = initial?.queryId != null && initial.queryId === answer?.queryId;

  return (
    <>
      <form
        className="ask-form"
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
      >
        <input
          className="ask-input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="问一个关于最近 AI 动态的问题…"
          maxLength={300}
          aria-label="问题"
        />
        <button className="button ask-submit" type="submit" disabled={loading}>
          {loading ? "检索中…" : "提问"}
        </button>
      </form>

      {/* Only before the first question: once there is an answer on screen the
          examples are clutter, and the history list below already offers
          things to re-read. */}
      {!answer && !loading && !streamed && (
        <div className="ask-examples">
          <span className="ask-examples-label">试试：</span>
          {EXAMPLES.map((example) => (
            <button
              key={example.question}
              type="button"
              className="ask-example"
              title={example.shows}
              onClick={() => {
                setQuestion(example.question);
                void ask(example.question);
              }}
            >
              {example.question}
              <span className="ask-example-shows">{example.shows}</span>
            </button>
          ))}
        </div>
      )}

      {/* The trace stays. It used to be removed the moment the answer landed,
          which threw away the one artefact that shows *how* the answer was
          reached — the thing that distinguishes this from a chat box. Open
          while running, collapsed once there is an answer to read first. */}
      {/* A cache hit runs no pipeline, so the four-step list has nothing to
          report and rendered as an empty box. Saying which layer answered is
          both more honest and more useful — a reader who sees a stale-looking
          answer should be able to tell it came from cache. */}
      {cacheHit && (
        <div className="ask-trace ask-cache-hit">
          <strong>命中缓存</strong>
          {cacheHit.outcome === "semantic" ? (
            <span className="ask-step-detail">
              语义近邻 · 相似度 {cacheHit.similarity?.toFixed(4)}
            </span>
          ) : (
            <span className="ask-step-detail">同一问题、同一份语料</span>
          )}
          <span className="ask-step-detail">未调用模型</span>
        </div>
      )}

      {stages.length > 0 && !cacheHit && (
        <details className="ask-trace" open={loading} aria-live="polite">
          <summary className="ask-trace-summary">
            检索过程
            {found ? <span className="ask-step-detail">{found} 条候选</span> : null}
            {evidence ? <span className="ask-step-detail">{evidence} 段证据</span> : null}
          </summary>
          <ol className="ask-progress">
            {STEPS.map((step) => {
              const isDone = done.has(step.key);
              // Active either because the server said this stage began, or
              // because it is the first stage not yet reported — the fast ones
              // send no "started" event, and inventing one would mean guessing
              // at a duration the server already knows.
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
      )}

      {error && (
        <div className="ask-answer" role="alert">
          <p className="filter-note">{error}</p>
        </div>
      )}

      {/* The answer while it is still being written. Rendered with the same
          renderer as the finished one, so the paragraph the reader starts on
          does not reflow when the final event lands. Citation markers show as
          plain numbers here and become clickable once the citation list arrives
          with the verified answer — the number itself never changes.

          `.ask-draft`, deliberately *not* `.ask-body`: a partial answer and a
          verified one must not look the same to anything reading the DOM.
          Reusing the class made "the answer has landed" indistinguishable from
          "the first sentence has landed", and three browser tests that had
          waited on `.ask-body` started asserting against a page whose sources
          had not been delivered yet. `aria-busy` says the same thing to a
          screen reader. */}
      {!answer && streamed && (
        <div className="ask-answer" aria-busy="true">
          <div className="ask-draft">{renderAnswerBody(streamed, [], () => {}, null)}</div>
          <p className="ask-meta ask-streaming" aria-live="polite">
            正在生成…
          </p>
        </div>
      )}

      {/* Earlier turns of this thread. Collapsed to question and conclusion:
          the full apparatus of every past answer would bury the current one,
          and each remains reachable by its permalink. */}
      {thread.length > 1 && (
        <ol className="ask-thread">
          {thread.slice(0, -1).map((turn, index) => (
            <li key={turn.queryId ?? index} className="ask-thread-turn">
              <p className="ask-thread-q">{turn.question}</p>
              <p className="ask-thread-a">
                {(turn.answerMarkdown || turn.refusalReason || "").slice(0, 140)}
                {(turn.answerMarkdown || "").length > 140 ? "…" : ""}
              </p>
              {turn.queryId && (
                <a className="ask-thread-link" href={`/ask/${turn.queryId}`}>
                  这一轮的完整回答 →
                </a>
              )}
            </li>
          ))}
        </ol>
      )}

      {answer && (
        <div className="ask-answer">
          {/* What the planner decided, before any of it was used. The absolute
              window matters most: "最近" became a real interval, and if it
              caught the wrong one the reader can see that rather than guess. */}
          {answer.plan && (
            <div className="ask-plan">
              {answer.plan.query_type && (
                <span className="ask-plan-chip">
                  {QUERY_TYPES[answer.plan.query_type] ?? answer.plan.query_type}
                </span>
              )}
              {answer.plan.time_range?.from && answer.plan.time_range?.to ? (
                <span className="ask-plan-chip">
                  {answer.plan.time_range.label ?? "时间范围"}
                  <span className="ask-plan-range">
                    {formatDate(answer.plan.time_range.from)} –{" "}
                    {formatDate(answer.plan.time_range.to)}
                  </span>
                </span>
              ) : (
                <span className="ask-plan-chip">全部时间</span>
              )}
              {/* Displaying the resolved window was half the promise. The site
                  already argued a reader who sees the wrong week should be able
                  to fix it rather than conclude the system is broken; until now
                  fixing it meant retyping the question and hoping. */}
              <details className="ask-window">
                <summary className="ask-window-toggle">改时间范围</summary>
                <div className="ask-window-body">
                  <label>
                    从
                    <input
                      type="date"
                      value={readerWindow?.from ?? (answer.plan?.time_range?.from ?? "").slice(0, 10)}
                      onChange={(event) =>
                        setReaderWindow((prev) => ({
                          from: event.target.value,
                          to: prev?.to ?? (answer.plan?.time_range?.to ?? "").slice(0, 10),
                        }))
                      }
                    />
                  </label>
                  <label>
                    到
                    <input
                      type="date"
                      value={readerWindow?.to ?? (answer.plan?.time_range?.to ?? "").slice(0, 10)}
                      onChange={(event) =>
                        setReaderWindow((prev) => ({
                          from: prev?.from ?? (answer.plan?.time_range?.from ?? "").slice(0, 10),
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
                        void ask(answer.question ?? question, readerWindow);
                      }
                    }}
                  >
                    用这个范围重问
                  </button>
                </div>
              </details>
              {answer.metrics?.evidence != null && (
                <span className="ask-plan-chip">{answer.metrics.evidence} 段证据</span>
              )}
              {/* How the question was read, not just what it asked. 「智谱」 also
                  searching for GLM is the difference between an answer and a
                  wrong "nothing was released"; showing it lets the reader tell
                  a good expansion from a wrong one. */}
              {answer.metrics?.aliases && answer.metrics.aliases.length > 0 && (
                <span className="ask-plan-chip ask-plan-alias">
                  同时检索
                  <span className="ask-plan-range">
                    {answer.metrics.aliases.slice(0, 4).join(" · ")}
                  </span>
                </span>
              )}
              {/* One publisher is not corroboration however many documents it
                  quotes, and the count was previously buried in the footer. */}
              {answer.metrics?.selection?.distinct_sources != null && (
                <span className="ask-plan-chip">
                  {answer.metrics.selection.distinct_sources} 家信源
                </span>
              )}
            </div>
          )}

          {/* The site answering about itself. Marked rather than blended in:
              it has no citations by construction, and a reader who has been
              told every fact carries a source should be able to see why this
              one does not instead of assuming they were lost. */}
          {/* A follow-up that was understood as something else. Shown for the
              same reason the resolved time window is: a reader whose 「它呢」 was
              tied to the wrong antecedent can see it rather than conclude the
              system is broken. */}
          {answer.rewrittenQuestion && (
            <p className="ask-rewrite" role="status">
              这是一个追问，已理解为：<strong>{answer.rewrittenQuestion}</strong>
            </p>
          )}

          {answer.kind === "corpus_stats" && (
            <p className="ask-kind" role="status">
              这是<strong>本站运行数据</strong>，直接来自数据库计数，不是检索结果，因此没有引用来源。
            </p>
          )}

          {/* Most of this answer's citations failed the support check. The
              signal existed and was spent on a line of small print identical to
              every other note — while the answer it belonged to stated that
              智谱 had released nothing, over a window holding three Zhipu items. */}
          {!answer.refused && answer.weakRetrieval && (
            <p className="ask-weak" role="status">
              这次检索的证据大多没通过支持度校验
              {answer.metrics?.support_dropped
                ? `（移除了 ${answer.metrics.support_dropped} 条引用）`
                : null}
              ，下面的结论可信度偏低，建议换个说法再问一次或放宽时间范围。
            </p>
          )}

          {answer.refused ? (
            <div className="ask-refusal">
              <strong>没有足够证据回答这个问题。</strong>
              <p>{answer.refusalReason ?? "检索到的内容不足以支持一个可核实的回答。"}</p>
              <p className="ask-refusal-note">
                这是刻意的：本站不会用模型的常识补答，没有来源支撑的内容不会显示。
              </p>

              {/* A refusal used to end here. The system knows exactly what it
                  read; showing it turns a dead end into something the reader
                  can act on — usually by noticing the window is wrong. */}
              {answer.considered?.length > 0 && (
                <div className="ask-considered">
                  <p className="ask-considered-title">检索到但不足以支撑回答的内容：</p>
                  <ul>
                    {answer.considered.slice(0, 5).map((row) => (
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
              {renderAnswerBody(
                answer.answerMarkdown,
                answer.citations,
                focusCitation,
                activeCite,
              )}
            </div>
          )}

          {answer.limitations.length > 0 && (
            <ul className="ask-limitations">
              {answer.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          )}

          {answer.citations.length > 0 && (
            <details className="ask-sources">
              <summary className="ask-sources-title">
                引用来源
                <span className="ask-sources-count">{answer.citations.length} 条</span>
              </summary>
              <ol className="ask-source-list">
                {answer.citations.map((citation) => {
                  const tier = TIERS[citation.sourceTier];
                  return (
                    <li
                      key={citation.number}
                      id={`cite-${citation.number}`}
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

          <p className="ask-meta">
            {answer.metrics?.total_ms && `耗时 ${(answer.metrics.total_ms / 1000).toFixed(1)}s`}
            {answer.citations.length > 0 &&
              ` · ${new Set(answer.citations.map((c) => c.sourceName)).size} 个信源`}
            {answer.metrics?.degraded?.length ? ` · 降级：${answer.metrics.degraded.join(", ")}` : ""}
            {/* Addressable. The id has always been returned with the answer;
                until there was a route that read it back it pointed nowhere. */}
            {answer.queryId && !isPermalink && (
              <>
                {" · "}
                <a className="ask-permalink" href={`/ask/${answer.queryId}`}>
                  永久链接
                </a>
              </>
            )}
          </p>

          {/* Directly under the answer it explains. Rendered after the history
              list it was unreadable — the reader had to scroll past twenty
              other conversations to reach the explanation of the one above. */}
          {answer.trace && answer.trace.length > 0 && <RetrievalTrace rows={answer.trace} />}
        </div>
      )}

      {/* Earlier conversations. Collapsed by default and one open at a time:
          a dozen expanded answers would bury the ask box that is the point of
          the page. */}
      {past.length > 0 && (
        <details className="ask-history">
          <summary className="ask-history-title">
            历史问答
            <span className="ask-history-count">{past.length} 条</span>
            <span className="ask-history-note">
              暂无账号体系，这里是本站的公共记录（M5 加鉴权后按人区分）
            </span>
          </summary>

          <ul className="ask-history-list">
            {past.map((row) => {
              const id = row.queryId ?? row.question ?? "";
              const isOpen = openHistory === id;
              return (
                <li key={id} className={`ask-history-row${isOpen ? " is-open" : ""}`}>
                  <button
                    type="button"
                    className="ask-history-head"
                    aria-expanded={isOpen}
                    onClick={() => setOpenHistory(isOpen ? null : id)}
                  >
                    <span className="ask-history-q">{row.question}</span>
                    <span className="ask-history-meta">
                      {row.refused ? (
                        <span className="ask-history-refused">已拒答</span>
                      ) : (
                        `${row.citations.length} 条引用`
                      )}
                      {row.askedAt && ` · ${formatDate(row.askedAt)}`}
                    </span>
                  </button>

                  {isOpen && (
                    <div className="ask-history-body">
                      {row.queryId && (
                        <p className="ask-meta">
                          <a className="ask-permalink" href={`/ask/${row.queryId}`}>
                            打开这条问答 ↗
                          </a>
                        </p>
                      )}
                      {row.refused ? (
                        <p className="filter-note">
                          {row.refusalReason ?? "检索到的内容不足以支持一个可核实的回答。"}
                        </p>
                      ) : (
                        <div className="ask-body">
                          {renderAnswerBody(row.answerMarkdown, row.citations, () => {}, null)}
                        </div>
                      )}

                      {row.citations.length > 0 && (
                        <ol className="ask-source-list">
                          {row.citations.map((citation) => (
                            <li key={citation.number} className="ask-source">
                              <span className="ask-source-no">[{citation.number}]</span>
                              <div>
                                <div className="ask-source-head">
                                  <a href={`/items/${citation.itemId}`}>{citation.title}</a>
                                  {TIERS[citation.sourceTier] && (
                                    <span
                                      className={`tier-badge ${TIERS[citation.sourceTier].className}`}
                                    >
                                      {TIERS[citation.sourceTier].label}
                                    </span>
                                  )}
                                </div>
                                <div className="ask-source-meta">
                                  {citation.sourceName}
                                  {citation.publishedAt && ` · ${formatDate(citation.publishedAt)}`}
                                  {" · "}
                                  <a
                                    href={citation.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    阅读原文 ↗
                                  </a>
                                </div>
                              </div>
                            </li>
                          ))}
                        </ol>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </>
  );
}

import { NextResponse } from "next/server";

/**
 * Browser-facing proxy for question answering.
 *
 * Generation lives in ai-service (AHR-ARCH-200 §3 puts embedding, rerank and
 * answer generation there, and keeps them out of core-api), which is only
 * reachable inside the Compose network. Relaying here keeps the internal
 * address internal rather than publishing an unauthenticated service.
 *
 * `?stream=1` relays the SSE progress stream instead of the single response.
 * The upstream body is piped through untouched — buffering it here to re-emit
 * would reintroduce exactly the wait the stream exists to remove.
 */

export const dynamic = "force-dynamic";

const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://ai-service:8000";

// Generation is a model round trip on top of three retrieval channels and a
// cross-encoder; the default fetch timeout would cut it off mid-answer.
const TIMEOUT_MS = 90_000;

const MAX_QUESTION_CHARS = 300;

export async function GET(request: Request) {
  // Suggestions for one answer, when asked for. Failure is silent by design:
  // no chips is a fine outcome, an error is not.
  const queryId = new URL(request.url).searchParams.get("suggestions");
  if (queryId) {
    try {
      const response = await fetch(
        `${AI_SERVICE_URL}/rag/suggestions/${encodeURIComponent(queryId)}`,
        { cache: "no-store" },
      );
      if (!response.ok) return NextResponse.json({ suggestions: [] });
      return NextResponse.json(await response.json(), {
        headers: { "cache-control": "no-store" },
      });
    } catch {
      return NextResponse.json({ suggestions: [] });
    }
  }

  // Conversation history. The rows have been accumulating in `rag_query` since
  // the first question; this is the read path that was missing, which is why
  // every answer used to vanish with the page that showed it.
  try {
    const response = await fetch(`${AI_SERVICE_URL}/rag/history`, { cache: "no-store" });
    if (!response.ok) {
      return NextResponse.json({ conversations: [] }, { status: 200 });
    }
    return NextResponse.json(await response.json(), {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    // History is an enhancement: failing to load it must not break the page.
    return NextResponse.json({ conversations: [] }, { status: 200 });
  }
}

/**
 * Carry the caller's address to ai-service.
 *
 * The quota is per caller, and ai-service identifies the caller from the first
 * `X-Forwarded-For` entry. This relay sat between the two and dropped it, so
 * every request arrived wearing this container's address: the anonymous limit of
 * 3/min and 20/day was being applied to the entire site at once rather than to
 * each visitor. Two people asking questions in the same minute would refuse each
 * other, and twenty questions would close the feature for everyone until
 * midnight — with nothing in the logs to say why.
 *
 * Caddy sets the header from the real connection; passing it through unchanged
 * keeps the original client in first position, which is the entry ai-service
 * reads. Locally there is no proxy and no header, so all callers share a bucket
 * — which is correct, because locally they are all the same caller.
 */
function forwardedFor(request: Request): Record<string, string> {
  const chain = request.headers.get("x-forwarded-for") ?? request.headers.get("x-real-ip");
  return chain ? { "x-forwarded-for": chain } : {};
}

/**
 * Pass `Cache-Control: no-cache` through to ai-service.
 *
 * Answers are cached (ADR-0017), and someone looking at a suspect answer needs
 * a way to re-run it against the live pipeline — "ask it again" does nothing
 * when the same cached row comes back. The standard directive already means
 * this, so it travels rather than being reinvented as a query parameter.
 */
function cacheDirective(request: Request): Record<string, string> {
  const directive = request.headers.get("cache-control");
  return directive ? { "cache-control": directive } : {};
}

export async function POST(request: Request) {
  const streaming = new URL(request.url).searchParams.get("stream") === "1";

  let question = "";
  // The reader's own time range, when they corrected the one the planner chose.
  let conversationId: string | undefined;
  let timeFrom: string | undefined;
  let timeTo: string | undefined;
  try {
    const body = (await request.json()) as {
      question?: unknown;
      timeFrom?: unknown;
      timeTo?: unknown;
      conversationId?: unknown;
    };
    question = String(body.question ?? "").trim();
    // Opaque to this layer: the upstream mints it and validates it, and a
    // malformed one starts a new thread there rather than failing here.
    if (typeof body.conversationId === "string" && body.conversationId.length <= 64) {
      conversationId = body.conversationId;
    }
    // Shape-checked here rather than passed through: the upstream would reject
    // a malformed date with a 422 the browser reports as "回答失败".
    const isDate = (v: unknown) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v);
    if (isDate(body.timeFrom) && isDate(body.timeTo)) {
      timeFrom = body.timeFrom as string;
      timeTo = body.timeTo as string;
    }
  } catch {
    return NextResponse.json({ error: "请求格式不正确" }, { status: 400 });
  }

  if (question.length < 2) {
    return NextResponse.json({ error: "问题太短了" }, { status: 400 });
  }
  if (question.length > MAX_QUESTION_CHARS) {
    return NextResponse.json({ error: "问题太长了" }, { status: 400 });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const path = streaming ? "/rag/ask/stream" : "/rag/ask";
    const response = await fetch(`${AI_SERVICE_URL}${path}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...forwardedFor(request),
        ...cacheDirective(request),
      },
      body: JSON.stringify({
        question,
        ...(conversationId ? { conversationId } : {}),
        ...(timeFrom && timeTo ? { timeFrom, timeTo } : {}),
      }),
      signal: controller.signal,
      cache: "no-store",
    });

    if (!response.ok) {
      console.error(`ai-service ${path} responded ${response.status}`);

      // A quota refusal is not a failure, and telling someone "请稍后重试" when
      // the answer is "you have used today's twenty" sends them into a retry
      // loop against a wall. ai-service already writes the reason in Chinese;
      // relay it, and keep the 429 so the client can tell the two apart.
      if (response.status === 429) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        return NextResponse.json(
          { error: body.detail ?? "提问过于频繁，请稍后再试。" },
          { status: 429, headers: { "retry-after": response.headers.get("retry-after") ?? "60" } },
        );
      }

      return NextResponse.json(
        { error: response.status === 503 ? "模型服务暂时不可用" : "回答失败，请稍后重试" },
        { status: 502 },
      );
    }

    if (streaming && response.body) {
      return new Response(response.body, {
        headers: {
          "content-type": "text/event-stream; charset=utf-8",
          "cache-control": "no-cache, no-transform",
          "x-accel-buffering": "no",
        },
      });
    }

    return NextResponse.json(await response.json(), {
      headers: { "cache-control": "no-store" },
    });
  } catch (error) {
    console.error(`ai-service ask unreachable:`, error);
    return NextResponse.json({ error: "回答超时，请稍后重试" }, { status: 504 });
  } finally {
    // The stream is piped, not awaited, so this only bounds establishing it.
    clearTimeout(timer);
  }
}

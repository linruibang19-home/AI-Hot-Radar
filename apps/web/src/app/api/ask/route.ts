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

export async function GET() {
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

export async function POST(request: Request) {
  const streaming = new URL(request.url).searchParams.get("stream") === "1";

  let question = "";
  try {
    const body = (await request.json()) as { question?: unknown };
    question = String(body.question ?? "").trim();
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
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
      cache: "no-store",
    });

    if (!response.ok) {
      console.error(`ai-service ${path} responded ${response.status}`);
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

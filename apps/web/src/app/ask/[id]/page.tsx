import { notFound } from "next/navigation";

import { AskPanel, type AnswerPayload } from "@/components/AskPanel";
import { BackLink } from "@/components/BackLink";

import type { Metadata } from "next";

/**
 * A single answer at its own address.
 *
 * Every answer has been written to `rag_query` since the feature shipped, and
 * the id was already returned to the browser — but with no route reading it
 * back, that id pointed at nothing. An answer could be produced, read once, and
 * then only be found again by scrolling the shared history list.
 *
 * Rendered on the server so a shared link carries the question in its title and
 * the answer in its HTML, rather than being an empty shell that fills in after
 * a fetch.
 */

export const dynamic = "force-dynamic";

const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://ai-service:8000";

async function load(id: string): Promise<AnswerPayload | null> {
  try {
    const response = await fetch(`${AI_SERVICE_URL}/rag/query/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as AnswerPayload;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const conversation = await load(id);
  if (!conversation) return { title: "问答记录" };

  return {
    title: conversation.question ?? "问答记录",
    description: conversation.refused
      ? "证据不足，本站拒绝回答这个问题。"
      : conversation.answerMarkdown.replace(/[[\]*#]/g, "").slice(0, 140),
  };
}

export default async function AskPermalinkPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const conversation = await load(id);
  if (!conversation) notFound();

  return (
    <>
      <header className="page-head">
        <BackLink href="/ask">返回问答</BackLink>
        <h1 className="page-title">{conversation.question}</h1>
        <p className="page-subtitle">
          这是一次已保存的问答记录 · 引用与检索计划均为当时生成 ·
          语料此后仍在更新，重新提问的结果可能不同
        </p>
      </header>

      {/* The same panel, seeded. Re-rendering the answer here with a second
          copy of the citation renderer would let the two drift — and the one
          that drifted would be the shared link, which is the copy other people
          see. The retrieval trace rides along inside `initial` and renders
          under the answer; only the permalink fetches it, because it is forty
          rows per question and the list page shows twenty questions. */}
      <AskPanel initial={conversation} />
    </>
  );
}

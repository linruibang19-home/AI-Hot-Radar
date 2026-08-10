import { AskPanel } from "@/components/AskPanel";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI 问答",
  description: "基于站内已采集资讯的问答，每条事实都标注来源，证据不足时明确拒答。",
};

export const dynamic = "force-dynamic";

export default function AskPage() {
  return (
    <>
      <header className="page-head">
        <h1 className="page-title">AI 问答</h1>
        <p className="page-subtitle">
          只依据站内已采集的资讯回答 · 每条事实标注来源并可跳回原文 · 证据不足时拒答而非猜测
        </p>
      </header>

      {/* The explanation of how retrieval works moved *inside* the panel, which
          renders it only before the first question. It is worth reading once,
          and a fixed block under a growing transcript is something the reader
          scrolls past on every turn to reach the box they are typing in. */}
      <AskPanel />
    </>
  );
}

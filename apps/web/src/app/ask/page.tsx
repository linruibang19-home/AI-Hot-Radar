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

      <AskPanel />

      <div className="notice">
        检索走的是<strong>混合召回 + 交叉编码器重排</strong>：稠密向量负责语义，
        关键词通道负责精确型号与版本号（纯语义检索会把 MXFP4 召回成 NVFP4），
        时间词解析成绝对区间后作为过滤条件。
        引用编号由服务端反查真实段落生成，<strong>模型自己写的来源不会被显示</strong>。
      </div>
    </>
  );
}

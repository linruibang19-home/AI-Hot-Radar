import { ModelSelector } from "./ModelSelector";
import { fetchGenerationModels } from "@/lib/api";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "模型配置",
  description: "查看并切换 DeepSeek 生成模型；检索向量与重排模型保持固定。",
};
export const dynamic = "force-dynamic";

export default async function ModelsPage() {
  const state = await fetchGenerationModels();
  return (
    <>
      <header className="page-head">
        <h1 className="page-title">模型配置</h1>
        <p className="page-subtitle">
          统一控制之后的内容整理、推荐理由、报告摘要与 RAG 回答 · 切换不重算历史内容
        </p>
      </header>
      <div className="notice">
        <strong>检索模型没有开放切换。</strong> embedding 与 reranker 继续使用硅基流动的既有配置，
        避免不同向量模型混入同一索引。DeepSeek V4 thinking 也保持显式关闭，确保现有 JSON
        校验、延迟和成本口径不被暗中改变。
      </div>
      {state ? <ModelSelector initial={state} /> : <div className="empty">暂时读不到模型配置。</div>}
    </>
  );
}

import { ModelSelector } from "./ModelSelector";
import { fetchGenerationModels, fetchGenerationProvider } from "@/lib/api";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "模型配置",
  description: "设置生成模型的地址、密钥与型号；检索向量与重排模型保持固定。",
};
export const dynamic = "force-dynamic";

export default async function ModelsPage() {
  const [state, provider] = await Promise.all([
    fetchGenerationModels(),
    fetchGenerationProvider(),
  ]);
  return (
    <>
      <header className="page-head">
        <h1 className="page-title">模型配置</h1>
        <p className="page-subtitle">决定之后的内容整理、报告与问答用哪个模型 · 不重算历史内容</p>
      </header>
      {state ? (
        <ModelSelector initial={state} provider={provider} />
      ) : (
        <div className="empty">暂时读不到模型配置。</div>
      )}
    </>
  );
}

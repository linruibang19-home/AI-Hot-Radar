"use client";

import type { GenerationModelState } from "@/lib/api";
import { useState } from "react";

export function ModelSelector({ initial }: { initial: GenerationModelState }) {
  const [state, setState] = useState(initial);
  const [token, setToken] = useState("");
  const [confirm, setConfirm] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState("");

  async function select(modelId: string) {
    setMessage("");
    if (!token || confirm !== modelId) {
      setMessage("请输入 OPERATOR 凭据，并完整填写要切换的模型 ID。 ");
      return;
    }
    setPending(modelId);
    try {
      const response = await fetch("/api/admin/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modelId, token, confirm, reason }),
      });
      const payload = (await response.json()) as {
        current?: GenerationModelState["current"];
        error?: string;
      };
      if (!response.ok || !payload.current) {
        setMessage(`切换失败：${payload.error ?? response.status}`);
        return;
      }
      setState((previous) => ({ ...previous, current: payload.current! }));
      setToken("");
      setConfirm("");
      setReason("");
      setMessage(`已切换到 ${payload.current.model_id}，只影响之后的新生成任务。`);
    } finally {
      setPending("");
    }
  }

  return (
    <>
      <div className="model-current">
        <span className="model-kicker">当前生成模型 · 配置 v{state.current.version}</span>
        <strong>{state.current.display_name}</strong>
        <code>{state.current.model_id}</code>
      </div>

      <div className="model-grid">
        {state.available.map((model) => {
          const active = model.model_id === state.current.model_id;
          return (
            <article className={`model-card${active ? " model-card-active" : ""}`} key={model.model_id}>
              <div className="model-card-head">
                <div>
                  <h2>{model.display_name}</h2>
                  <code>{model.model_id}</code>
                </div>
                <span className="state">{active ? "当前" : "可切换"}</span>
              </div>
              <p>{model.description}</p>
              <dl className="model-metrics">
                <div><dt>上下文</dt><dd>{(model.context_window_tokens / 1_000_000).toFixed(0)}M</dd></div>
                <div><dt>输入</dt><dd>¥{model.input_cny_per_million}/M</dd></div>
                <div><dt>缓存输入</dt><dd>¥{model.cached_input_cny_per_million}/M</dd></div>
                <div><dt>输出</dt><dd>¥{model.output_cny_per_million}/M</dd></div>
              </dl>
              {!active && (
                <button className="button" disabled={pending !== ""} onClick={() => select(model.model_id)}>
                  {pending === model.model_id ? "切换中…" : `切换到 ${model.display_name}`}
                </button>
              )}
            </article>
          );
        })}
      </div>

      <section className="model-operator">
        <h2>执行切换</h2>
        <p>凭据只用于这一次请求，保存在当前页面内存中；不会写入 localStorage、数据库或日志。</p>
        <label>
          OPERATOR Bearer Token
          <input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} />
        </label>
        <label>
          确认模型 ID
          <input value={confirm} onChange={(event) => setConfirm(event.target.value)} placeholder="例如 deepseek-v4-pro" />
        </label>
        <label>
          切换原因（审计记录，可选）
          <input value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)} />
        </label>
        {message && <p className="model-message" role="status">{message}</p>}
      </section>
    </>
  );
}

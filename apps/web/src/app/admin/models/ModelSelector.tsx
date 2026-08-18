"use client";

import type { GenerationModelState, GenerationProviderState } from "@/lib/api";
import { useEffect, useState } from "react";

type Pending = { kind: "provider" } | { kind: "reset" } | { kind: "model"; modelId: string };

export function ModelSelector({
  initial,
  provider,
}: {
  initial: GenerationModelState;
  provider: GenerationProviderState | null;
}) {
  const [models, setModels] = useState(initial);
  const [source, setSource] = useState(provider);
  const [baseUrl, setBaseUrl] = useState(provider?.baseUrl ?? "");
  const [apiKey, setApiKey] = useState("");
  const [revealKey, setRevealKey] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!pending) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) setPending(null);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [pending, busy]);

  async function run() {
    if (!pending || !token.trim()) {
      setMessage("请输入管理密钥。");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const payload =
        pending.kind === "model"
          ? { action: "select", modelId: pending.modelId, confirm: pending.modelId }
          : pending.kind === "reset"
            ? { action: "provider-reset" }
            : { action: "provider", baseUrl: baseUrl.trim(), apiKey: apiKey.trim() };

      const response = await fetch("/api/admin/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, token: token.trim() }),
      });
      const result = (await response.json()) as Record<string, unknown>;

      if (!response.ok) {
        setMessage(explain(result.error as string | undefined, response.status));
        return;
      }

      if (pending.kind === "model") {
        setModels((previous) => ({
          ...previous,
          current: result.current as GenerationModelState["current"],
        }));
        setMessage(`已切换到 ${(result.current as { model_id: string }).model_id}。`);
      } else {
        const next = result as unknown as GenerationProviderState;
        setSource(next);
        setBaseUrl(next.baseUrl);
        // Cleared on success: the value is stored now, and a key left sitting in
        // a form field is a key that can be read off an unattended screen.
        setApiKey("");
        setMessage(pending.kind === "reset" ? "已改回使用环境变量。" : "供应商已保存并验证。");
      }
      setPending(null);
      setToken("");
    } catch {
      setMessage("请求没有完成，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  const storageBlocked = source !== null && !source.credentialStorageReady;

  return (
    <>
      {message && (
        <p className="model-message" role="status">
          {message}
        </p>
      )}

      <section className="panel">
        <div className="panel-head">
          <h2>供应商</h2>
          {source?.usesEnvironment ? (
            <span className="tag">环境变量</span>
          ) : (
            source && <span className="tag tag-quiet">已保存 · v{source.version}</span>
          )}
        </div>

        <div className="panel-body">
          <label className="field">
            请求地址
            <input
              type="url"
              autoComplete="off"
              spellCheck={false}
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://api.deepseek.com"
            />
          </label>

          <label className="field">
            <span className="field-label">
              API Key
              <button className="link" type="button" onClick={() => setRevealKey((on) => !on)}>
                {revealKey ? "隐藏" : "显示"}
              </button>
            </span>
            <input
              // Not typed or named like a password: a password-typed field
              // invites the browser's manager to autofill a saved credential
              // over a pasted key, and both render as the same row of dots.
              type={revealKey ? "text" : "password"}
              name="ahr-provider-credential"
              autoComplete="off"
              data-lpignore="true"
              data-1p-ignore=""
              data-form-type="other"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={source?.keyFromEnvironment ? "来自环境变量" : "留空则沿用已保存的"}
            />
          </label>
        </div>

        <div className="panel-foot">
          <span>
            {storageBlocked
              ? "未配置加密密钥，暂时不能保存"
              : source?.keyFingerprint
                ? `当前密钥 ${source.keyFingerprint}`
                : "保存前会先验证一次"}
          </span>
          <div className="panel-actions">
            {source && !source.usesEnvironment && (
              <button className="button" type="button" onClick={() => setPending({ kind: "reset" })}>
                改回环境变量
              </button>
            )}
            <button
              className="button button-primary"
              type="button"
              disabled={storageBlocked || !baseUrl.trim()}
              onClick={() => setPending({ kind: "provider" })}
            >
              保存
            </button>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>生成模型</h2>
          <span className="tag tag-quiet">检索模型固定</span>
        </div>
        <ul className="model-list">
          {models.available.map((model) => {
            const active = model.model_id === models.current.model_id;
            return (
              <li key={model.model_id} className={active ? "model-row model-row-active" : "model-row"}>
                <div>
                  <strong>{model.display_name}</strong>
                  <p>
                    输入 ¥{model.input_cny_per_million} · 输出 ¥{model.output_cny_per_million} · 每百万
                    tokens
                  </p>
                </div>
                {active ? (
                  <span className="tag">当前</span>
                ) : (
                  <button
                    className="button"
                    type="button"
                    onClick={() => setPending({ kind: "model", modelId: model.model_id })}
                  >
                    切换
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {pending && (
        <div
          className="sheet-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !busy) setPending(null);
          }}
        >
          <section className="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
            <h2 id="sheet-title">
              {pending.kind === "model"
                ? `切换到 ${pending.modelId}`
                : pending.kind === "reset"
                  ? "改回环境变量"
                  : "保存供应商"}
            </h2>
            <label className="field">
              管理密钥
              <input
                autoFocus
                type="password"
                name="ahr-site-operator"
                autoComplete="off"
                data-lpignore="true"
                data-1p-ignore=""
                data-form-type="other"
                value={token}
                onChange={(event) => setToken(event.target.value)}
              />
            </label>
            {message && (
              <p className="model-message" role="status">
                {message}
              </p>
            )}
            <div className="sheet-actions">
              <button className="button" type="button" disabled={busy} onClick={() => setPending(null)}>
                取消
              </button>
              <button className="button button-primary" type="button" disabled={busy} onClick={run}>
                {busy ? "处理中…" : "确认"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

/** Short, actionable, one sentence. The page is not the place for a manual. */
export function explain(error: string | undefined, status: number): string {
  const known: Record<string, string> = {
    provider_auth_failed: "供应商拒绝了这个 API Key，请核对后重试。",
    provider_endpoint_not_found: "这个地址上没有找到 API，请检查是否漏了或多了路径。",
    provider_returned_html: "这个地址返回的是网页而不是 API。",
    provider_unreachable: "连不上这个地址。",
    provider_rejected: "供应商拒绝了这次请求。",
    invalid_provider_url: "请求地址不是有效的 URL。",
    api_key_required: "第一次保存需要填写 API Key。",
    credential_storage_unavailable: "本站未配置加密密钥，不能保存 API Key。",
    invalid_selection: "提交内容不完整。",
    operator_credential_required: "请输入管理密钥。",
    idempotency_key_reused: "请刷新页面后重试。",
    request_in_progress: "上一次请求还在进行中。",
    cross_origin_rejected: "同源校验失败，请刷新页面。",
  };
  if (status === 401 || status === 403) return "管理密钥不正确。";
  return known[error ?? ""] ?? `操作失败（${error ?? status}）。`;
}

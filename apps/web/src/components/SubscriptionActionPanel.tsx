"use client";

import { useState } from "react";
import Link from "next/link";

type Action = "confirm" | "unsubscribe";

const COPY: Record<Action, { title: string; description: string; button: string; success: string }> = {
  confirm: {
    title: "确认邮件订阅",
    description: "确认后，所选日报、周报或月报会按邮箱对应的订阅设置投递。",
    button: "确认订阅",
    success: "订阅已生效。下一期已发布报告会按计划发送。",
  },
  unsubscribe: {
    title: "取消邮件订阅",
    description: "取消后不再发送新的报告邮件，站内阅读和历史报告不会受影响。",
    button: "确认取消订阅",
    success: "邮件订阅已取消。",
  },
};

export function SubscriptionActionPanel({ action, token }: { action: Action; token: string }) {
  const copy = COPY[action];
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState(token ? "" : "链接缺少必要令牌，请重新从邮件打开。");
  const [succeeded, setSucceeded] = useState(false);

  async function apply() {
    if (!token || pending) return;
    setPending(true);
    setMessage("");
    try {
      const response = await fetch(`/api/subscriptions/${action}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const payload = (await response.json().catch(() => ({}))) as { detail?: string };
      setSucceeded(response.ok);
      setMessage(response.ok ? copy.success : (payload.detail ?? "链接无效或已经过期。"));
    } catch {
      setSucceeded(false);
      setMessage("订阅服务暂时不可用，请稍后重试。");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="subscription-action-page">
      <section className="subscription-action-card" aria-labelledby="subscription-action-title">
        <span>AI HOT RADAR · EMAIL</span>
        <h1 id="subscription-action-title">{copy.title}</h1>
        <p>{copy.description}</p>
        {message ? (
          <p className={succeeded ? "subscription-action-result is-success" : "subscription-action-result"} aria-live="polite">
            {message}
          </p>
        ) : null}
        {!succeeded ? (
          <button type="button" onClick={apply} disabled={!token || pending}>
            {pending ? "正在处理…" : copy.button}
          </button>
        ) : (
          <Link href="/reports">返回报告</Link>
        )}
      </section>
    </main>
  );
}

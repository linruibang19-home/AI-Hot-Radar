"use client";

import { useEffect, useRef, useState } from "react";

import type { FormEvent } from "react";
import type { ReportPeriod } from "@/lib/api";

const PERIOD_OPTIONS: Array<{ value: ReportPeriod; label: string; note: string }> = [
  { value: "daily", label: "日报", note: "每天" },
  { value: "weekly", label: "周报", note: "每周" },
  { value: "monthly", label: "月报", note: "每月" },
];

export function ReportSubscribe({ period }: { period: ReportPeriod }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [email, setEmail] = useState("");
  const [periods, setPeriods] = useState<ReportPeriod[]>([period]);
  // The first client render must match SSR. Detecting the browser zone in the
  // state initializer rendered UTC on the Node host and Asia/Shanghai in the
  // browser, producing a hydration error even while the dialog was closed.
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [succeeded, setSucceeded] = useState(false);

  useEffect(() => {
    setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai");
  }, []);

  function togglePeriod(value: ReportPeriod) {
    setPeriods((current) =>
      current.includes(value) ? current.filter((entry) => entry !== value) : [...current, value],
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (periods.length === 0) {
      setSucceeded(false);
      setMessage("请至少选择一种报告周期。");
      return;
    }

    setPending(true);
    setMessage("");
    try {
      const response = await fetch("/api/subscriptions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, periods, timezone }),
      });
      const payload = (await response.json().catch(() => ({}))) as { message?: string; detail?: string };
      setSucceeded(response.ok);
      setMessage(
        response.ok
          ? (payload.message ?? "确认邮件已发送，请前往邮箱完成订阅。")
          : (payload.detail ?? "订阅暂时失败，请稍后重试。"),
      );
    } catch {
      setSucceeded(false);
      setMessage("网络暂时不可用，请稍后重试。");
    } finally {
      setPending(false);
    }
  }

  function open() {
    setMessage("");
    setSucceeded(false);
    dialog.current?.showModal();
  }

  return (
    <>
      <button className="report-subscribe-trigger" type="button" onClick={open}>
        邮件订阅
      </button>
      <dialog className="report-subscribe-dialog" ref={dialog} aria-labelledby="subscribe-title">
        <form method="dialog" className="report-subscribe-close">
          <button type="submit" aria-label="关闭订阅窗口">×</button>
        </form>
        <form className="report-subscribe-form" onSubmit={submit}>
          <span className="report-subscribe-eyebrow">REPORT DELIVERY</span>
          <h2 id="subscribe-title">把报告送到邮箱</h2>
          <p>
            订阅整期 AI 行业简报，不会逐条发送动态。我们会先发送确认链接，未经确认不会投递。
          </p>

          <ol className="report-subscribe-flow" aria-label="邮件订阅流程">
            <li><strong>1</strong><span>发送确认邮件<small>链接 24 小时有效</small></span></li>
            <li><strong>2</strong><span>你点击确认<small>防止他人冒用邮箱</small></span></li>
            <li><strong>3</strong><span>投递下一期报告<small>含摘要、在线原文与退订链接</small></span></li>
          </ol>

          <label className="report-subscribe-email">
            <span>邮箱地址</span>
            <input
              type="email"
              name="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              maxLength={320}
              placeholder="name@example.com"
              required
            />
          </label>

          <fieldset>
            <legend>推送周期</legend>
            <div className="report-subscribe-periods">
              {PERIOD_OPTIONS.map((option) => (
                <label key={option.value}>
                  <input
                    type="checkbox"
                    checked={periods.includes(option.value)}
                    onChange={() => togglePeriod(option.value)}
                  />
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.note} 08:30</small>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <p className="report-subscribe-timezone">
            按 {timezone} 当地时间 08:30 后投递已发布的下一期报告；不会补发确认前的历史期刊，
            可随时从邮件退订。
          </p>
          {message ? (
            <p className={succeeded ? "report-subscribe-result is-success" : "report-subscribe-result"} aria-live="polite">
              {message}
            </p>
          ) : null}
          <button className="report-subscribe-submit" type="submit" disabled={pending || succeeded}>
            {pending ? "正在发送…" : succeeded ? "确认邮件已申请" : "发送确认邮件"}
          </button>
          {succeeded ? <p className="report-subscribe-hint">请检查收件箱和垃圾邮件箱，并在 24 小时内完成确认。</p> : null}
        </form>
      </dialog>
    </>
  );
}

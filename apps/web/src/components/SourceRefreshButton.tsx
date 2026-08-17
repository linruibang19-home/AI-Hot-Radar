"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

export function SourceRefreshButton() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [requested, setRequested] = useState(false);

  function refresh() {
    setRequested(true);
    startTransition(() => router.refresh());
  }

  const label = isPending ? "刷新中…" : requested ? "已读取最新状态" : "刷新状态";

  return (
    <button
      className="button source-refresh"
      type="button"
      onClick={refresh}
      disabled={isPending}
      aria-live="polite"
    >
      {label}
    </button>
  );
}

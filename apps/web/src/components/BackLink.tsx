"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * The "back to the list" pill.
 *
 * Extracted rather than copied a third time: the item detail page had the
 * treatment, the story and topic pages had a bare "← 返回…" text link, and the
 * inconsistency was visible on screen. One component means the next page that
 * needs it cannot drift again.
 *
 * It goes *back* rather than to a fixed destination whenever the reader arrived
 * from somewhere on this site. Following a citation out of an answer and then
 * being offered only "返回全部动态" dropped people onto a list they had never
 * been on, several steps from the question they were in the middle of reading.
 * `href` remains the destination for anyone arriving cold — a shared link, a
 * search result — where there is no history to return to.
 */
export function BackLink({ href, children }: { href: string; children: string }) {
  const router = useRouter();
  const [cameFromSite, setCameFromSite] = useState(false);
  const [label, setLabel] = useState(children);

  useEffect(() => {
    // `document.referrer` is empty on a direct visit and cross-origin when the
    // reader came from elsewhere; either way the fixed destination is right.
    const referrer = document.referrer;
    if (!referrer) return;
    try {
      const from = new URL(referrer);
      if (from.origin !== window.location.origin) return;
      if (from.pathname === window.location.pathname) return;
      setCameFromSite(true);
      if (from.pathname.startsWith("/ask")) setLabel("返回问答");
    } catch {
      /* malformed referrer: fall back to the fixed destination */
    }
  }, []);

  const icon = (
    <svg
      className="back-link-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </svg>
  );

  if (cameFromSite) {
    return (
      <button className="back-link" type="button" onClick={() => router.back()}>
        {icon}
        {label}
      </button>
    );
  }

  return (
    <Link className="back-link" href={href}>
      {icon}
      {children}
    </Link>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { SidebarResizer } from "@/components/SidebarResizer";

/**
 * Primary navigation.
 *
 * A client component only because the active route has to be highlighted, which
 * needs usePathname. Everything it renders is static, so this costs one small
 * bundle and no data fetching.
 */

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const ICONS: Record<string, ReactNode> = {
  curated: <path d="M13 2 3 14h8l-1 8 10-12h-8l1-8z" />,
  feed: (
    <>
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <circle cx="3.5" cy="6" r="1" />
      <circle cx="3.5" cy="12" r="1" />
      <circle cx="3.5" cy="18" r="1" />
    </>
  ),
  hot: <path d="M12 2s5 4.5 5 9a5 5 0 0 1-10 0c0-1.5.6-2.8 1.4-3.8C9 9.5 12 7 12 2z" />,
  report: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <line x1="8" y1="8" x2="16" y2="8" />
      <line x1="8" y1="12" x2="16" y2="12" />
      <line x1="8" y1="16" x2="13" y2="16" />
    </>
  ),
  ask: (
    <>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </>
  ),
  topics: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  story: (
    <>
      <path d="M4 5h10a2 2 0 0 1 2 2v12H6a2 2 0 0 1-2-2z" />
      <path d="M16 8h2a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-2" />
      <line x1="8" y1="9" x2="12" y2="9" />
      <line x1="8" y1="13" x2="12" y2="13" />
    </>
  ),
  admin: (
    <>
      <path d="M12 2 4 6v6c0 5 3.4 9.1 8 10 4.6-.9 8-5 8-10V6z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  eval: (
    <>
      <path d="M3 3v18h18" />
      <path d="m7 15 4-5 3 3 5-7" />
    </>
  ),
  ops: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
};

interface NavEntry {
  href: string;
  label: string;
  icon: keyof typeof ICONS;
}

const SECTIONS: { label: string; entries: NavEntry[] }[] = [
  {
    label: "内容",
    entries: [
      { href: "/", label: "精选", icon: "curated" },
      { href: "/items", label: "全部 AI 动态", icon: "feed" },
      { href: "/hot", label: "热点榜", icon: "hot" },
      { href: "/stories", label: "事件聚合", icon: "story" },
      { href: "/reports", label: "AI 日报", icon: "report" },
      { href: "/topics", label: "主题地图", icon: "topics" },
      { href: "/ask", label: "AI 问答", icon: "ask" },
    ],
  },
  {
    // The evaluation record and the source health page are both "how do you
    // know it works" rather than content, so they sit together.
    label: "工程",
    entries: [
      { href: "/eval", label: "检索评测", icon: "eval" },
      { href: "/ops", label: "成本与延迟", icon: "ops" },
      { href: "/admin/models", label: "模型配置", icon: "admin" },
      { href: "/admin/sources", label: "信源后台", icon: "admin" },
    ],
  },
];

/**
 * The home route matches only exactly; every other route also matches its
 * children, so an item detail page keeps 全部 AI 动态 highlighted.
 */
function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function Sidebar() {
  const pathname = usePathname() ?? "/";

  return (
    <aside className="sidebar">
      <Link className="brand" href="/">
        <span className="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="3.2" fill="currentColor" stroke="none" />
          </svg>
        </span>
        AI HOT RADAR
      </Link>

      {SECTIONS.map((section) => (
        <nav
          key={section.label}
          className="nav-section"
          aria-label={`${section.label}导航`}
        >
          <h2 className="nav-label" id={`nav-${section.label}`}>
            {section.label}
          </h2>
          <ul className="nav-list" aria-labelledby={`nav-${section.label}`}>
            {section.entries.map((entry) => {
              const active = isActive(pathname, entry.href);
              return (
                <li key={entry.href}>
                  <Link
                    className={active ? "nav-link nav-link-active" : "nav-link"}
                    href={entry.href}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon>{ICONS[entry.icon]}</Icon>
                    {entry.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      ))}

      <SidebarResizer />
    </aside>
  );
}

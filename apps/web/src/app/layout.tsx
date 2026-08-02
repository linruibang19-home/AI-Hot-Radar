import type { Metadata, Viewport } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import "./globals.css";

const SITE_URL = process.env.PUBLIC_BASE_URL ?? "http://localhost:3000";
const SITE_NAME = "AI Hot Radar";
const DESCRIPTION =
  "AI 行业时效情报平台：自动采集官方信源与权威媒体，去重、结构化并精选，每条内容都可追溯到原文。";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: SITE_NAME,
    // Sub-pages set their own title; this keeps the brand suffix consistent.
    template: `%s · ${SITE_NAME}`,
  },
  description: DESCRIPTION,
  applicationName: SITE_NAME,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    title: SITE_NAME,
    description: DESCRIPTION,
    locale: "zh_CN",
    url: SITE_URL,
  },
  twitter: { card: "summary", title: SITE_NAME, description: DESCRIPTION },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#0f6e5c",
  width: "device-width",
  initialScale: 1,
};

const NAV = [
  { href: "/", label: "精选" },
  { href: "/items", label: "全部 AI 动态" },
  { href: "/reports", label: "AI 日报" },
  { href: "/topics", label: "主题地图" },
];

const ADMIN_NAV = [{ href: "/admin/sources", label: "信源后台" }];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        {/* Keyboard users should not have to tab through the whole nav on
            every page (WCAG 2.4.1). */}
        <a className="skip-link" href="#main">
          跳转到主要内容
        </a>

        <div className="layout">
          <aside className="sidebar">
            <div className="brand">AI HOT RADAR</div>

            <nav aria-label="内容导航">
              <div className="nav-label" id="nav-content">
                内容
              </div>
              <ul className="nav-list" aria-labelledby="nav-content">
                {NAV.map((entry) => (
                  <li key={entry.href}>
                    <Link className="nav-link" href={entry.href}>
                      {entry.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>

            <nav aria-label="管理导航">
              <div className="nav-label" id="nav-admin">
                管理
              </div>
              <ul className="nav-list" aria-labelledby="nav-admin">
                {ADMIN_NAV.map((entry) => (
                  <li key={entry.href}>
                    <Link className="nav-link" href={entry.href}>
                      {entry.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </aside>

          <main className="main" id="main">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Hot Radar",
  description: "AI 行业时效情报平台：自动发现、核验与压缩 AI 行业信息",
};

const NAV = [
  { href: "/", label: "精选" },
  { href: "/items", label: "全部 AI 动态" },
  { href: "/reports", label: "AI 日报" },
  { href: "/topics", label: "主题" },
];

const ADMIN_NAV = [{ href: "/admin/sources", label: "信源后台" }];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="layout">
          <aside className="sidebar">
            <div className="brand">AI HOT RADAR</div>
            <div className="nav-label">内容</div>
            {NAV.map((entry) => (
              <Link key={entry.href} className="nav-link" href={entry.href}>
                {entry.label}
              </Link>
            ))}
            <div className="nav-label">管理</div>
            {ADMIN_NAV.map((entry) => (
              <Link key={entry.href} className="nav-link" href={entry.href}>
                {entry.label}
              </Link>
            ))}
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}

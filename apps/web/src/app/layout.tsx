import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Sidebar } from "@/components/Sidebar";

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
          <Sidebar />
          <main className="main" id="main">
            <div className="main-inner">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}

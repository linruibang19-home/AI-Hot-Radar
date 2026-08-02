import Link from "next/link";

import type { CategoryTab } from "@/lib/api";

/**
 * Category navigation rendered as links rather than client-side state.
 *
 * Each tab is a real URL, so a filtered view can be shared, bookmarked and
 * crawled, and the page keeps working without JavaScript. The active tab is
 * marked with aria-current so screen readers announce it (WCAG 4.1.2).
 */
export function CategoryTabs({
  tabs,
  active,
  basePath,
  params = {},
}: {
  tabs: CategoryTab[];
  active: string;
  basePath: string;
  params?: Record<string, string | undefined>;
}) {
  if (tabs.length === 0) return null;

  const href = (key: string) => {
    const query = new URLSearchParams();
    for (const [name, value] of Object.entries(params)) {
      if (value) query.set(name, value);
    }
    if (key !== "all") query.set("category", key);
    const suffix = query.toString();
    return suffix ? `${basePath}?${suffix}` : basePath;
  };

  return (
    <nav className="tabs" aria-label="内容分类">
      {tabs.map((tab) => {
        const current = tab.key === active;
        return (
          <Link
            key={tab.key}
            href={href(tab.key)}
            className={current ? "tab tab-active" : "tab"}
            aria-current={current ? "page" : undefined}
          >
            {tab.label}
            <span className="tab-count">{tab.total}</span>
          </Link>
        );
      })}
    </nav>
  );
}

/** Search box that preserves the active category across a submit. */
export function SearchBox({
  action,
  defaultValue,
  category,
}: {
  action: string;
  defaultValue?: string;
  category?: string;
}) {
  return (
    <form method="get" action={action} className="searchbox" role="search">
      {/* Without this the active tab is silently dropped on submit. */}
      {category && category !== "all" && (
        <input type="hidden" name="category" value={category} />
      )}
      <input
        type="search"
        name="q"
        defaultValue={defaultValue ?? ""}
        placeholder="搜索标题/摘要/正文…"
        className="searchbox-input"
        aria-label="搜索内容"
      />
      <button type="submit" className="searchbox-button">
        搜索
      </button>
    </form>
  );
}

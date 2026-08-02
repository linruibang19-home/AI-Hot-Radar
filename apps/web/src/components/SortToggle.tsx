import Link from "next/link";

const OPTIONS = [
  { key: "curated", label: "按精选日" },
  { key: "latest", label: "按发布时间" },
  { key: "heat", label: "按热度" },
];

/** Sort switch for the curated feed, kept URL-driven like the category tabs. */
export function SortToggle({
  active,
  basePath,
  params = {},
}: {
  active: string;
  basePath: string;
  params?: Record<string, string | undefined>;
}) {
  const href = (key: string) => {
    const query = new URLSearchParams();
    for (const [name, value] of Object.entries(params)) {
      if (value) query.set(name, value);
    }
    if (key !== "curated") query.set("sort", key);
    const suffix = query.toString();
    return suffix ? `${basePath}?${suffix}` : basePath;
  };

  return (
    <div className="sort-row" role="group" aria-label="排序方式">
      <span className="sort-label">排序</span>
      {OPTIONS.map((option) => {
        const current = option.key === active;
        return (
          <Link
            key={option.key}
            href={href(option.key)}
            className={current ? "sort-option sort-option-active" : "sort-option"}
            aria-current={current ? "true" : undefined}
          >
            {option.label}
          </Link>
        );
      })}
    </div>
  );
}

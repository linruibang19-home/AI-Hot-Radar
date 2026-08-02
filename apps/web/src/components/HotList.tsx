import Link from "next/link";

import { CONTENT_TYPE_LABELS } from "@/components/ItemCard";
import type { HotItem } from "@/lib/api";

/**
 * The "当前热点" rail.
 *
 * Heat is deliberately not shown as a raw number: `hot_score` is unbounded and
 * decays continuously, so a reader comparing "41.2" against "38.7" would be
 * reading precision the score does not have. Rank plus the corroboration count
 * is what the number actually supports.
 */
export function HotList({ items }: { items: HotItem[] }) {
  if (items.length === 0) return null;

  return (
    <aside className="hot-panel" aria-labelledby="hot-heading">
      <h2 className="hot-heading" id="hot-heading">
        当前热点
        <span className="hot-note">按时效与来源权重排序</span>
      </h2>

      <ol className="hot-list">
        {items.map((item, index) => (
          <li className="hot-row" key={item.id}>
            <span className={index < 3 ? "hot-rank hot-rank-top" : "hot-rank"}>
              {index + 1}
            </span>
            <div className="hot-body">
              <Link className="hot-title" href={`/items/${item.id}`}>
                {item.title}
              </Link>
              <div className="hot-meta">
                <span>{item.sourceName}</span>
                {item.contentType && (
                  <span>· {CONTENT_TYPE_LABELS[item.contentType] ?? item.contentType}</span>
                )}
                {item.independentSources > 1 && (
                  <span className="tag tag-primary">
                    {item.independentSources} 家信源
                  </span>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </aside>
  );
}

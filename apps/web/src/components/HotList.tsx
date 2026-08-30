import Link from "next/link";

import type { HotItem } from "@/lib/api";
import { heatBadge, showsHeatBadge } from "@/lib/heat";

/**
 * The 当前热点 panel.
 *
 * Compact by design: it sits above the feed, so it shows a short leaderboard
 * and links to the full ranking rather than competing with the timeline for
 * vertical space.
 */
export function HotList({
  items,
  limit = 5,
  showMore = true,
}: {
  items: HotItem[];
  limit?: number;
  showMore?: boolean;
}) {
  if (items.length === 0) return null;
  const shown = items.slice(0, limit);

  return (
    <section className="hot-panel" aria-labelledby="hot-heading">
      <div className="hot-head">
        <h2 className="hot-heading" id="hot-heading">
          当前热点
        </h2>
        {showMore && (
          <Link className="hot-more" href="/hot">
            完整榜单 →
          </Link>
        )}
      </div>

      <ol className="hot-list">
        {shown.map((item, index) => (
          <li className="hot-row" key={item.id}>
            <span className={index < 3 ? "hot-rank hot-rank-top" : "hot-rank"}>
              {index + 1}
            </span>
            <Link className="hot-title" href={`/items/${item.id}`}>
              {item.title}
            </Link>
            {/* The rank on the left already says which is hotter, so a row
                reading "3 … 0 热度" only contradicts itself. */}
            {showsHeatBadge(item.heat) && (
              <span className="hot-score">
                {heatBadge(item.heat)} <span className="hot-score-unit">热度</span>
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

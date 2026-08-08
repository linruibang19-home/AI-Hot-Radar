import { formatTime } from "@/lib/datetime";

import { BackLink } from "@/components/BackLink";

import { ItemCard } from "@/components/ItemCard";
import { TimelineDay, TimelineRow } from "@/components/Timeline";
import { fetchVendorItems, fetchVendorMap, groupByDay } from "@/lib/api";

import type { Metadata } from "next";

/**
 * Everything about one company or model family.
 *
 * Deliberately the same layout as a topic page. The two are different queries —
 * this one joins through `item_entity`, that one through `item_topic` — but to
 * a reader they are the same act, and giving them different shapes would make
 * the difference look meaningful when it is only an implementation detail.
 */

export const dynamic = "force-dynamic";

const OPEN_DAYS = 3;

/** Read the card back so the page shows the vendor's name, not its slug. */
async function findVendor(slug: string) {
  const vendors = await fetchVendorMap();
  return vendors.find((vendor) => vendor.slug === slug) ?? null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const vendor = await findVendor(slug);
  return {
    title: vendor?.name ?? slug,
    description: vendor?.description ?? undefined,
  };
}

export default async function VendorDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const [items, vendor] = await Promise.all([fetchVendorItems(slug, 40), findVendor(slug)]);
  const groups = groupByDay(items);

  return (
    <>
      <p className="page-subtitle" style={{ marginBottom: 10 }}>
        <BackLink href="/topics">返回主题地图</BackLink>
      </p>

      <header className="page-head">
        <h1 className="page-title">{vendor?.name ?? slug}</h1>
        <p className="page-subtitle">
          公司与模型 · {vendor?.description ?? "该厂商相关的全部内容"} · 共 {items.length} 条
        </p>
      </header>

      {items.length === 0 ? (
        // A curated vendor with nothing this week is a true statement about
        // coverage, not an error page.
        <div className="empty">该厂商暂无内容。</div>
      ) : (
        [...groups.entries()].map(([day, dayItems], index) => (
          <TimelineDay
            key={day}
            day={day}
            count={dayItems.length}
            defaultOpen={index < OPEN_DAYS}
          >
            {dayItems.map((item) => (
              <TimelineRow
                key={item.id}
                time={formatTime(item.publishedAt ?? item.observedAt)}
              >
                <ItemCard item={item} />
              </TimelineRow>
            ))}
          </TimelineDay>
        ))
      )}
    </>
  );
}

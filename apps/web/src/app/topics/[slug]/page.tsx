import { formatTime } from "@/lib/datetime";
import Link from "next/link";

import { BackLink } from "@/components/BackLink";

import { ItemCard } from "@/components/ItemCard";
import { TimelineDay, TimelineRow } from "@/components/Timeline";
import { fetchTopicItems, fetchTopicMap, groupByDay } from "@/lib/api";

import type { Metadata } from "next";

export const dynamic = "force-dynamic";

const OPEN_DAYS = 3;

/** Look the topic up in the map so the page shows its name, not its slug. */
async function findTopic(slug: string) {
  const groups = await fetchTopicMap();
  for (const group of groups) {
    const match = group.children.find((child) => child.slug === slug);
    if (match) return { topic: match, group };
  }
  return null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const found = await findTopic(slug);
  return {
    title: found?.topic.name ?? slug,
    description: found?.topic.description ?? undefined,
  };
}

export default async function TopicDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const [items, found] = await Promise.all([fetchTopicItems(slug, 40), findTopic(slug)]);
  const groups = groupByDay(items);

  return (
    <>
      <p className="page-subtitle" style={{ marginBottom: 10 }}>
        <BackLink href="/topics">返回主题地图</BackLink>
      </p>

      <header className="page-head">
        <h1 className="page-title">{found?.topic.name ?? slug.replace(/_/g, " ")}</h1>
        <p className="page-subtitle">
          {found?.group.name ? `${found.group.name} · ` : ""}
          {found?.topic.description ?? "该主题下的全部内容"} · 共 {items.length} 条
        </p>
      </header>

      {items.length === 0 ? (
        <div className="empty">该主题暂无内容。</div>
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

import Link from "next/link";
import { cache } from "react";

import { BackLink } from "@/components/BackLink";
import { ItemCard } from "@/components/ItemCard";
import { TimelineDay, TimelineRow } from "@/components/Timeline";
import { formatPublicationTime } from "@/lib/datetime";
import { fetchTopicFeed, fetchTopicMap, groupByDay } from "@/lib/api";

import type { Metadata } from "next";

export const dynamic = "force-dynamic";

const OPEN_DAYS = 3;

const findTopic = cache(async (slug: string) => {
  const groups = await fetchTopicMap();
  for (const group of groups) {
    const match = group.children.find((child) => child.slug === slug);
    if (match) return { topic: match, group };
  }
  return null;
});

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
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ cursor?: string }>;
}) {
  const [{ slug }, query] = await Promise.all([params, searchParams]);
  const [feed, found] = await Promise.all([
    fetchTopicFeed(slug, query.cursor),
    findTopic(slug),
  ]);
  const items = feed.data.map((row) => row.item);
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
          {found?.topic.description ?? "该主题下的全部内容"} · 共 {feed.total} 条
        </p>
        <p className="association-updated">
          只展示置信度达到公开门槛且每篇排名前三的主题标签，降低泛化误贴。
        </p>
      </header>

      {items.length === 0 ? (
        <div className="empty">该主题暂无达到公开门槛的内容。</div>
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
                time={formatPublicationTime(
                  item.source.id,
                  item.publishedAt,
                  item.observedAt,
                )}
              >
                <div className="association-context">
                  <span>正文结构化主题</span>
                  <small>已通过公开置信门槛</small>
                </div>
                <ItemCard item={item} />
              </TimelineRow>
            ))}
          </TimelineDay>
        ))
      )}

      <nav className="feed-pagination" aria-label="主题内容分页">
        {query.cursor && <Link href={`/topics/${slug}`}>返回第一页</Link>}
        {feed.page.hasMore && feed.page.nextCursor && (
          <Link
            className="feed-next"
            href={`/topics/${slug}?cursor=${encodeURIComponent(feed.page.nextCursor)}`}
          >
            继续浏览 →
          </Link>
        )}
      </nav>
    </>
  );
}

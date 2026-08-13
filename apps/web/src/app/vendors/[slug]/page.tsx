import Link from "next/link";
import { cache } from "react";

import { BackLink } from "@/components/BackLink";
import { ItemCard } from "@/components/ItemCard";
import { TimelineDay, TimelineRow } from "@/components/Timeline";
import { formatDateTime, formatPublicationTime } from "@/lib/datetime";
import {
  fetchVendorFeed,
  fetchVendorMap,
  groupByDay,
  normaliseVendorRelation,
} from "@/lib/api";

import type { VendorFeedItem, VendorRelation } from "@/lib/api";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";

const OPEN_DAYS = 3;

const RELATIONS: Record<
  VendorRelation,
  { label: string; empty: string; description: string }
> = {
  primary: {
    label: "核心动态",
    empty: "该厂商暂无核心动态。",
    description: "标题或摘要核心在讲该厂商及其模型",
  },
  related: {
    label: "相关与对比",
    empty: "该厂商暂无相关或对比内容。",
    description: "厂商作为比较对象、合作方或受影响主体",
  },
  mention: {
    label: "顺带提及",
    empty: "该厂商暂无顺带提及内容。",
    description: "正文出现过，但不是文章的主要讨论对象",
  },
};

const REASONS: Record<string, string> = {
  subject_in_title: "标题直接命中",
  subject_in_summary_lead: "摘要核心命中",
  subject_context: "正文主语",
  comparison_or_object: "对比或关联对象",
  title_mention: "标题相关提及",
  passing_mention: "正文顺带提及",
};

const findVendor = cache(async (slug: string) => {
  const vendors = await fetchVendorMap();
  return vendors.find((vendor) => vendor.slug === slug) ?? null;
});

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
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ relation?: string; cursor?: string }>;
}) {
  const [{ slug }, query] = await Promise.all([params, searchParams]);
  const relation = normaliseVendorRelation(query.relation);
  const [feed, vendor] = await Promise.all([
    fetchVendorFeed(slug, relation, query.cursor),
    findVendor(slug),
  ]);
  const items = feed.data.map((row) => row.item);
  const rowsById = new Map(feed.data.map((row) => [row.item.id, row]));
  const groups = groupByDay(items);
  const counts: Record<VendorRelation, number> = {
    primary: vendor?.total ?? (relation === "primary" ? feed.total : 0),
    related: vendor?.relatedTotal ?? (relation === "related" ? feed.total : 0),
    mention: vendor?.mentionTotal ?? (relation === "mention" ? feed.total : 0),
  };

  return (
    <>
      <p className="page-subtitle" style={{ marginBottom: 10 }}>
        <BackLink href="/topics">返回主题地图</BackLink>
      </p>

      <header className="page-head">
        <h1 className="page-title">{vendor?.name ?? slug}</h1>
        <p className="page-subtitle">
          公司与模型 · {vendor?.description ?? "该厂商相关内容"}
        </p>
        <p className="association-updated">
          关联由结构化实体与正文位置共同判定
          {feed.updatedAt ? ` · 最近刷新 ${formatDateTime(feed.updatedAt)}` : ""}
        </p>
      </header>

      <nav className="relation-tabs" aria-label="厂商内容关联层级">
        {(Object.keys(RELATIONS) as VendorRelation[]).map((key) => (
          <Link
            key={key}
            href={`/vendors/${slug}?relation=${key}`}
            className={key === relation ? "relation-tab relation-tab-active" : "relation-tab"}
            aria-current={key === relation ? "page" : undefined}
          >
            <strong>{RELATIONS[key].label}</strong>
            <span>{counts[key]}</span>
          </Link>
        ))}
      </nav>

      <div className="association-explainer">
        <strong>{RELATIONS[relation].label}</strong>
        <span>{RELATIONS[relation].description}，当前共 {feed.total} 条。</span>
      </div>

      {items.length === 0 ? (
        <div className="empty">{RELATIONS[relation].empty}</div>
      ) : (
        [...groups.entries()].map(([day, dayItems], index) => (
          <TimelineDay
            key={day}
            day={day}
            count={dayItems.length}
            defaultOpen={index < OPEN_DAYS}
          >
            {dayItems.map((item) => {
              const row = rowsById.get(item.id) as VendorFeedItem;
              return (
                <TimelineRow
                  key={item.id}
                  time={formatPublicationTime(
                    item.source.id,
                    item.publishedAt,
                    item.observedAt,
                  )}
                >
                  <div className="association-context">
                    <span>{REASONS[row.reasonCode] ?? "可追溯实体关联"}</span>
                    <small>命中实体：{row.matchedEntity.replaceAll("-", " ")}</small>
                  </div>
                  <ItemCard item={item} />
                </TimelineRow>
              );
            })}
          </TimelineDay>
        ))
      )}

      <nav className="feed-pagination" aria-label="厂商内容分页">
        {query.cursor && (
          <Link href={`/vendors/${slug}?relation=${relation}`}>返回第一页</Link>
        )}
        {feed.page.hasMore && feed.page.nextCursor && (
          <Link
            className="feed-next"
            href={`/vendors/${slug}?relation=${relation}&cursor=${encodeURIComponent(feed.page.nextCursor)}`}
          >
            继续浏览 →
          </Link>
        )}
      </nav>
    </>
  );
}

import Link from "next/link";

import { fetchContentTypeMap, fetchTopicMap, fetchVendorMap } from "@/lib/api";

import type { MapCard } from "@/lib/api";
import type { Metadata } from "next";

/**
 * The topic map, in several dimensions rather than one.
 *
 * It used to show only the controlled topic vocabulary, which answers "what is
 * this about" and nothing else. Two questions a reader asks just as often —
 * "what has OpenAI been doing" and "show me only the papers" — were already
 * answerable from data the pipeline had been writing since M2, and neither had
 * a read path: `entity` (677 companies, 832 models) and
 * `content_item.content_type` (11 values, 8.7% null) were both unused here.
 *
 * So this is several sections over several sources, not one vocabulary with
 * company names bolted into it. Bolting them in would have been worse: a topic
 * is what a piece is *about*, a vendor is who it is *about*, and merging them
 * forces "OpenAI's multimodal work" to pick one.
 */

export const metadata: Metadata = {
  title: "主题地图",
  description: "AI 主题地图：按公司与模型、技术方向、产业政策与内容形态浏览。",
};

export const dynamic = "force-dynamic";

function CardGrid({ cards, href }: { cards: MapCard[]; href: (slug: string) => string }) {
  return (
    <div className="topic-cards">
      {cards.map((card) => (
        <Link
          key={card.slug}
          className={card.total === 0 ? "topic-card topic-card-empty" : "topic-card"}
          href={href(card.slug)}
        >
          <h3 className="topic-card-name">{card.name}</h3>
          {card.description && <p className="topic-card-desc">{card.description}</p>}
          <span className="topic-card-link">
            查看 <strong>{card.total}</strong> 条内容 →
          </span>
        </Link>
      ))}
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="topic-group">
      <h2 className="topic-group-head">
        {title}
        {description && <span className="topic-group-desc">{description}</span>}
      </h2>
      {children}
    </section>
  );
}

export default async function TopicsPage() {
  // Three independent reads rather than one combined endpoint: they have
  // different shapes and different cache keys, and a single payload would make
  // the page wait for the slowest of them.
  const [groups, vendors, contentTypes] = await Promise.all([
    fetchTopicMap(),
    fetchVendorMap(),
    fetchContentTypeMap(),
  ]);

  const topicCount = groups.reduce((sum, group) => sum + group.children.length, 0);
  const total = topicCount + vendors.length + contentTypes.length;

  return (
    <>
      <section className="hero">
        <p className="hero-eyebrow">
          <span className="hero-rule" aria-hidden="true" />
          TOPICS · 主题地图
        </p>
        <h1 className="hero-title">按主题看 AI</h1>
        <p className="hero-lead">
          公司与模型、技术方向、产业与政策、内容形态——{total}{" "}
          个入口，分别由实体抽取、受控主题词表与内容类型三条管线持续更新，
          点进任何一个看近期焦点与全部内容。
        </p>
      </section>

      {vendors.length > 0 && (
        <Section
          title="公司与模型"
          description="按厂商与模型系追踪：谁发了什么、又赢了哪一局"
        >
          <CardGrid cards={vendors} href={(slug) => `/vendors/${slug}`} />
        </Section>
      )}

      {groups.map((group) => (
        <Section key={group.slug} title={group.name} description={group.description ?? ""}>
          <CardGrid cards={group.children} href={(slug) => `/topics/${slug}`} />
        </Section>
      ))}

      {contentTypes.length > 0 && (
        <Section title="内容形态" description="按内容类型浏览：论文、教程、观点、政策……">
          {/* `type:` forces an exact content_type rather than a tab lookup. Two
              tab keys collide with content types (`tutorial` covers tutorial *and*
              open_source), so without the prefix a card reading "查看 28 条" would
              open a 52-item list and contradict itself. */}
          <CardGrid
            cards={contentTypes}
            href={(slug) => `/items?category=type%3A${slug}`}
          />
        </Section>
      )}

      {groups.length === 0 && vendors.length === 0 && (
        <div className="empty">尚无主题数据。请先运行内容加工。</div>
      )}
    </>
  );
}

import Link from "next/link";

import { fetchTopicMap } from "@/lib/api";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "主题地图",
  description: "AI 主题地图：模型能力、工程实践、生态工具链与产业政策四条主线。",
};

export const dynamic = "force-dynamic";

export default async function TopicsPage() {
  const groups = await fetchTopicMap();
  const topicCount = groups.reduce((sum, group) => sum + group.children.length, 0);

  return (
    <>
      <section className="hero">
        <p className="hero-eyebrow">
          <span className="hero-rule" aria-hidden="true" />
          TOPICS · 主题地图
        </p>
        <h1 className="hero-title">按主题看 AI</h1>
        <p className="hero-lead">
          {groups.map((group) => group.name).join("、")}——{topicCount}{" "}
          个主题由 AI 标签归一到受控词表、持续更新，点进任何一个看近期焦点与全部内容。
        </p>
      </section>

      {groups.length === 0 ? (
        <div className="empty">尚无主题数据。请先运行内容加工。</div>
      ) : (
        groups.map((group) => (
          <section key={group.slug} className="topic-group">
            <h2 className="topic-group-head">
              {group.name}
              {group.description && (
                <span className="topic-group-desc">{group.description}</span>
              )}
            </h2>

            <div className="topic-cards">
              {group.children.map((topic) => (
                <Link
                  key={topic.slug}
                  className={topic.total === 0 ? "topic-card topic-card-empty" : "topic-card"}
                  href={`/topics/${topic.slug}`}
                >
                  <h3 className="topic-card-name">{topic.name}</h3>
                  {topic.description && (
                    <p className="topic-card-desc">{topic.description}</p>
                  )}
                  <span className="topic-card-link">
                    查看 <strong>{topic.total}</strong> 条内容 →
                  </span>
                </Link>
              ))}
            </div>
          </section>
        ))
      )}
    </>
  );
}

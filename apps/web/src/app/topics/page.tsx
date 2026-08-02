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
  const covered = groups.reduce((sum, group) => sum + group.total, 0);

  return (
    <>
      <h1 className="page-title">主题地图</h1>
      <p className="page-subtitle">
        主题由 AI 抽取后归一到受控词表（config/taxonomy.yaml）——未命中词表的标签会被丢弃，
        而不是新建一个主题，因此这张地图的形状是固定的，只有覆盖量在变
      </p>

      {groups.length === 0 ? (
        <div className="empty">尚无主题数据。请先运行内容加工。</div>
      ) : (
        <>
          <div className="stat-row">
            <div className="stat">
              <div className="stat-value">{groups.length}</div>
              <div className="stat-label">主线</div>
            </div>
            <div className="stat">
              <div className="stat-value">
                {groups.reduce((sum, group) => sum + group.children.length, 0)}
              </div>
              <div className="stat-label">受控主题</div>
            </div>
            <div className="stat">
              <div className="stat-value">{covered}</div>
              <div className="stat-label">已打标条目</div>
            </div>
          </div>

          {groups.map((group) => (
            <section key={group.slug} className="topic-group">
              <h2 className="day-heading">
                {group.name}
                <span className="day-count">{group.total} 条</span>
              </h2>
              {group.description && <p className="topic-group-desc">{group.description}</p>}

              <div className="topic-cards">
                {group.children.map((topic) => (
                  <Link
                    key={topic.slug}
                    className={topic.total === 0 ? "topic-card topic-card-empty" : "topic-card"}
                    href={`/topics/${topic.slug}`}
                  >
                    <div className="topic-card-head">
                      <span className="topic-card-name">{topic.name}</span>
                      <span className="topic-card-count">{topic.total}</span>
                    </div>
                    {topic.description && (
                      <p className="topic-card-desc">{topic.description}</p>
                    )}
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </>
  );
}

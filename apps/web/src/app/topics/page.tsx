import Link from "next/link";

import { fetchTopics } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function TopicsPage() {
  const topics = await fetchTopics();

  return (
    <>
      <h1 className="page-title">主题</h1>
      <p className="page-subtitle">
        主题由 AI 抽取后归一到受控词表（config/taxonomy.yaml），未命中的标签会被丢弃而不是新建主题
      </p>

      {topics.length === 0 ? (
        <div className="empty">尚无主题数据。请先运行内容加工。</div>
      ) : (
        <div className="topic-grid">
          {topics.map((topic) => (
            <Link key={topic.slug} className="topic-chip" href={`/topics/${topic.slug}`}>
              {topic.name}
              <span className="topic-chip-count">{topic.total}</span>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

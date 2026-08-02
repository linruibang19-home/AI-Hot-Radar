import Link from "next/link";

import { ItemCard } from "@/components/ItemCard";
import { fetchTopicItems } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function TopicDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const items = await fetchTopicItems(slug, 40);

  return (
    <>
      <p className="page-subtitle">
        <Link href="/topics">← 返回主题列表</Link>
      </p>

      <h1 className="page-title">{slug.replace(/_/g, " ")}</h1>
      <p className="page-subtitle">该主题下的全部内容，按发布时间倒序 · {items.length} 条</p>

      {items.length === 0 ? (
        <div className="empty">该主题暂无内容。</div>
      ) : (
        items.map((item) => <ItemCard key={item.id} item={item} />)
      )}
    </>
  );
}

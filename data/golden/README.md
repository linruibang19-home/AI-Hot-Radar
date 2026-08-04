# RAG 黄金集

评测方案见 [`docs/design/m4-rag-evaluation.md`](../../docs/design/m4-rag-evaluation.md)。
六个类别各 15 题，合计 90 题，满足 `AHR-RAG-400` §14（六类各 ≥15）与
`AHR-ROADMAP-800` M4（80+ 题）。

## 为什么在 `content_item` 层标注，而不是 `content_chunk` 层

规格 §14 要求「分块或融合权重变化都必须跑回归」，而分块一旦变化，
chunk id 全部作废——按 chunk 标注的黄金集会**在最需要它的那一刻失效**。
本项目已经因为分块缺陷重切过一次全量语料。

因此 `relevant_items` 记的是 `content_item.id`，它跨重新分块、跨重新嵌入都稳定。
评测时把召回的 chunk 映射回它所属的 item 再计分：

```
chunk → content_revision.content_item_id → 与 relevant_items 比对
```

代价是**粒度变粗**：召回了同一篇文章的错误段落也算命中。
这个代价是清醒接受的——Recall 的用途是回答"相关文档进候选集了吗"，
段落级精度由 `citation` 相关指标在生成阶段单独衡量。

## 事实必须来自原文，不能来自 `zh_title`

`content_item.zh_title` 与 `summary_zh` 是 enrichment LLM 生成的，
按锁定约束 **LLM 输出不是可信事实**。实际已经发现偏差：某条 `zh_title` 写
「商汤开源4K直出轻量多模态模型 SenseNova U1.5」，原文是
「预览了 SenseNova U1.5-Lite-Preview」——丢掉了 Lite 与 Preview 两个限定。

所以本目录每道题的答案都对着 `content_revision.body_text` 核过。

## 字段

```yaml
- id: RAG-GOLD-001              # 稳定编号，不复用
  category: recent_updates       # 六类之一
  question: "..."                # 用户会怎么问，不是检索关键词
  asked_at: 2026-08-03T12:00:00+08:00   # 时间题的解析基准，必须固定否则不可复现
  answerable: true               # false = 该拒答
  relevant_items:                # 分级相关性，供 nDCG 使用
    - id: <uuid>
      grade: 2                   # 2 = 直接回答问题；1 = 相关支撑但不足以单独作答
  must_contain: ["9931"]         # 可选：正确答案必须出现的字符串
  must_not_claim: ["..."]        # 可选：诱导题的反向断言
  probe: "..."                   # 可选：人工复核该题标注时用的检索词
  notes: "..."                   # 可选：这题在考什么
```

`grade` 只有 2 和 1 两档。更细的分级在只有一个标注者时不可靠，
虚假的精度比粗粒度更糟。

## 覆盖检查

`ahr rag-eval --validate` 会校验：编号唯一、每类 15 题、所有 `relevant_items.id`
在库中存在且未被标为重复、`answerable: false` 的题不得有 `relevant_items`。

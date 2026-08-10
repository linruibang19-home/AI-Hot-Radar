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
  evidence_must_contain: ["..."] # 可选：原始正文必须出现；生成标题/摘要不算证据
  must_not_claim: ["..."]        # 可选：诱导题的反向断言
  cohort: zh_vendor_to_latin_model # 可选：专项分组
  distractor_items:               # 可选：同快照噪声 A/B 的真实近邻原文
    - id: <uuid>
      reason: "为什么容易混淆"
  probe: "..."                   # 可选：人工复核该题标注时用的检索词
  notes: "..."                   # 可选：这题在考什么
```

`grade` 只有 2 和 1 两档。更细的分级在只有一个标注者时不可靠，
虚假的精度比粗粒度更糟。

## Planner 标注（`AHR-QSO-700` §8）

§8 要求 `entity/time planner accuracy ≥ 0.90`。08-10 已用 category 代理量过 query-type：
正则 0.6667、LLM 0.9067；但六种 query type 扫描显示 89.7% 题的 Recall@10 完全相同，
所以该代理在当前语料上**不可作为发布判据**，也不能把默认关闭的 LLM 数字当线上通过。
下一步应单独标注实体解析和绝对时间窗，而不是把 category 自动回填成“正确答案”。

Planner 值得量：`query_type` 与 `freshness_required` 决定三件事——
时间窗是否过滤稠密/稀疏通道、`source_fit` 查哪一行亲和度、`temporal_fit` 是否生效。
**分错类是静默的**，不报错，只是安静地检索了错误的时段或偏好了错误的信源类型。

三个字段全部可选，**每道题可以只标其中一个**：

```yaml
  expected_query_type: recent_updates   # 六类之一，见 planner.QUERY_TYPES
  expected_time: {from: 2026-07-27, to: 2026-08-02}   # 期望的时间窗，按本地日期
  # 或者，当这道题本来就不该有时间窗时（解释型问题就是这样）：
  expected_time: no_window
  expected_entities: ["Cloudflare"]     # 问句里应当被识别出的实体名
```

### 三条标注规则

**① 按问句该被理解成什么标，不要按 Planner 的规则推。**
拿 §3 的默认值反推期望值等于让实现和自己对答案，测不出任何东西。
要标的是**读者问这句话时的意思**，这也是这份标注无法自动生成的原因。

**② `expected_time` 写绝对日期，不写「上周」。**
`asked_at` 每题固定，所以期望窗口是一对确定的日子，人可以算一次、用眼睛复核；
写成短语则要交给正在被测的那段代码去解释。
边界按**实际覆盖到的那一天**写：`上周` 的窗口右端是下周一 00:00，
覆盖到周日为止，所以标 `to: 周日`（比较时已处理这个半开区间）。

**③ `no_window` 是一种期望，不是「没标」。**
字段缺失 = 这道题不参与 planner 计分；`no_window` = 断言「不该解析出任何时间窗」。
两者在报告里是不同的东西，前者进不了分母。

### 跑法

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli rag-eval --variant planner
```

**这个变体不连数据库、不调任何供应商**（Planner 是问句与 `asked_at` 的纯函数），
所以它免费、可进 CI、断网可跑。

报告里 `annotation_coverage` 与准确率**永远并排出现**：
四道题上的 1.00 不是一条通过的门禁，读者不能只看到分子。
标注数为 0 时命令**以非零码退出**——把「不可判定」显示成「看起来没问题」是更糟的那种状态。

## 覆盖检查

`ahr rag-eval --validate` 会校验：编号唯一、主集每类 15 题、所有 `relevant_items.id`
和 `distractor_items.id` 在库中存在且未被标为重复、`answerable: false` 的题不得有
`relevant_items`。`--validate-original-evidence` 还会在原始正文中检查
`evidence_must_contain`，并明确排除生成标题和摘要。

`vendor-alias/` 是独立的 15 题专项集，不混入主 90 题趋势。它用
`rag-eval --variant specialist-ab` 在一次进程内冻结通道和候选顺序，再比较 control、
entity 与 noise 三个实验臂。最新证据见
`docs/status/rag-specialist-audit-20260811.md`。

`expected_query_type` 不在受控词表内、`expected_time` 缺 `from`/`to` 或首尾颠倒，
都会在加载时硬失败——一个拼错的类型名会被当成永久的 planner 失败，
而那是标注的错不是系统的错。

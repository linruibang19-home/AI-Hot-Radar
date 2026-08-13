# 10｜RAG 评测、发布门与实验解释

## 1. `/eval` 页面是什么

它展示版本化离线实验的摘要和发布门，不会随每次页面刷新重新跑 90 道题。只有语料快照、检索
策略、生成模型、prompt、后处理或黄金标注改变时，才运行新评测并提交结果。动态运行状态在
`/ops`，两者不能混称实时监控。

## 2. 黄金集

主集 90 题，覆盖近期动态、时间线、比较、事实核查、原理解释和不可答。每题有 asked_at、时区、
相关 item、等级、must contain、禁止结论等标注。另有厂商别名/噪声专项集，验证中文名、型号和
竞争近邻。

黄金集本身也要校验：题号唯一、时间带时区、answerable 必须有 relevant items、unanswerable
不能偷偷携带答案、每类样本足够。

## 3. 检索指标

| 指标 | 回答的问题 | 局限 |
|---|---|---|
| Recall@k | 相关文档是否进入前 k | 不关心排序早晚 |
| MRR | 第一个相关结果有多靠前 | 只看首个命中 |
| nDCG@k | 多个不同等级结果的整体排序 | 依赖标注等级 |
| source diagnostics | 是否被单一来源垄断 | 不是相关性指标 |

指标以 item 去重，否则同一文章多个 chunk 会虚增 Recall。线上引用是 chunk 粒度，检索评测的
相关性可在 item 粒度，这两个层次要明确。

## 4. B1–B13 应该怎么读

每一轮只改变一个假设并保留负结果：

- B1：纯稠密基线；
- B2：加入稀疏但简单交错，总体下降，证明融合方法有问题；
- B3：RRF + 时间过滤改善近期问题，但其他类下降，推动 reranker；
- B4：交叉编码器显著提升；
- B7：时效融合；
- B8：扫描权重组合，接上 rerank 后差距很小，结论“不改”；
- B9/B10/B12：受控维度、元数据和自适应深度；
- B13：CJK bigram 修通道但端到端几乎不变，保留证据而非宣传。

页面卡片的“改了什么、判据、结果”是实验审计记录，不是自动调参器，也不会自行刷新数字。

## 5. 生成指标

- citation coverage：事实句是否带引用；
- citation precision/support：被引段是否支持；
- story coverage：应覆盖的相关事件是否被表达；
- must contain hit：关键事实是否出现；
- refusal on unanswerable / over-refusal；
- presupposition assertion：是否把诱导前提当事实；
- forbidden term/claim；
- latency p50/p95/max；
- 平均引用数和支持均值。

自动支持度只能用于回归和筛查。高风险数值和发布正确性保留人工抽检。

## 6. 发布门

发布门至少组合：主集 Recall、事实句引用完整率、段落支持率、可答题误拒、诱导题误断言和人工
抽检。任何单一总分都可能掩盖严重退化。门槛变更必须说明样本、模型和风险，而不是为了让新轮
通过而临时下调。

## 7. 为什么保留负结果

B2、B8、B13 和 GEN/GEN-FIX 展示了工程判断：

- 局部指标提升可能让总体变差；
- 扫描几十组权重不代表必须选新权重；
- 修复基础检索通道不一定改变最终排序；
- 最终失败可能在解析出口而不是检索。

这类证据比只展示最终高分更能说明系统性实验能力。

## 8. 如何更新评测

1. 固定语料 snapshot/fingerprint；
2. 记录代码提交、配置、模型、prompt 和价目；
3. 运行黄金集 schema 校验；
4. 先跑 retrieval，再 generation/specialist/latency；
5. 比较分类型指标和失败样本；
6. 对高风险样本人工审计；
7. 只有达到门槛才更新发布摘要；
8. 原始 JSON 和旧轮次永不覆盖。

## 9. 代码与证据

- `apps/ai-service/src/ahr/rag/eval/`
- `apps/ai-service/tests/test_rag_eval.py`
- `data/golden/`
- `docs/status/eval/`
- `docs/status/product/rag-specialist-audit-20260811.md`


# 22｜90 题黄金集、RAG 质量页与发布门禁

`/eval` 不是线上问答流量的实时排行榜，也不是模型自评页面。它把固定问题、原文标注、版本化实验输出和发布阈值汇总成一个可审计快照：修改检索、切块、重排、prompt 或引用出口之后，都能回答“同一批题变好还是变坏”。

## 1. 90 题黄金集是什么

主集位于 `data/golden/*.yaml`，六类各 15 题：

| 类别 | 想验证什么 | 典型风险 |
|---|---|---|
| `recent_updates` | 最近时间窗内的新动态 | 时间解析错、旧内容排名过高 |
| `timeline` | 事件/产品按时间串联 | 版本混淆、漏掉关键节点 |
| `comparison` | 两个对象的相同维度比较 | 只召回一方、不同口径硬比 |
| `fact_check` | 对具体断言核真 | 相似文章替代直接证据 |
| `explainer` | 原理、机制、限制解释 | 召回关键词多但不支持结论 |
| `abstention` | 证据不足时拒答 | 被问题前提诱导，编造不存在事实 |

当前固定构成是 78 道可回答、12 道不可回答。题目数量是数据文件加载和 schema 校验的结果，不是前端手写统计。

## 2. 一道题在 YAML 里包含什么

```yaml
- id: RAG-GOLD-001
  category: recent_updates
  question: "用户真实会问的句子"
  asked_at: 2026-08-03T12:00:00+08:00
  answerable: true
  relevant_items:
    - id: <稳定 content_item UUID>
      grade: 2
  must_contain: ["答案必须出现的关键字符串"]
  evidence_must_contain: ["必须在原始 revision 正文里找到的文本"]
  must_not_claim: ["诱导题中绝不能断言的内容"]
  distractor_items:
    - id: <真实近邻噪声 item UUID>
      reason: "为什么容易被误召回"
```

`asked_at` 固定相对日期的解析基准，否则“最近一周”每次运行都变题。`grade=2` 表示能直接回答，`grade=1` 表示相关支撑但不能单独作答。`answerable=false` 题禁止带 relevant item，防止标注自相矛盾。

标注落在稳定 `content_item.id`，不是 chunk id：切块算法变化正是必须跑回归的时候，如果黄金集绑 chunk，重切会让整套答案同时作废。评测时把召回 chunk 反查 revision/item 后再与相关 item 比对；段落是否真的支持结论由生成与 citation 指标另行评价。

## 3. 黄金集加载时先做哪些硬校验

`ahr.rag.eval.golden` 会在检索前检查：

- 题号唯一、类别在受控集合内、主集每类数量满足约束；
- 时间带时区，时间窗首尾有效；
- 可回答题必须有相关 item，不可回答题不得伪装 relevant item；
- relevant / distractor UUID 在数据库存在、未被错误标成重复；
- `evidence_must_contain` 必须出现在原始 `content_revision.body_text`，不能只出现在 AI 生成的 `zh_title`/`summary_zh`；
- planner 可选标注中的 query type、实体和绝对时间窗符合 schema。

黄金集本身有错时命令非零退出，不能把“没有可用标注”显示为 100%。

## 4. 一轮检索评测怎样执行

```text
加载 90 题 + 验证原始证据
  → 对每题用固定 asked_at 生成 RetrievalPlan
  → bge-m3 query embedding
  → pgvector dense 召回 + PostgreSQL FTS sparse 召回
  → 时间/元数据过滤
  → RRF 融合
  → bge-reranker-v2-m3 交叉编码器重排
  → 折叠同 item 的多个 chunk
  → 与 relevant_items 比对
  → 输出逐题 ranked result、run/config/corpus/model 快照与聚合指标
```

### 检索指标

| 指标 | 回答的问题 | 注意 |
|---|---|---|
| Recall@10 / @20 | 标注相关 item 是否至少有一个进入前 K | 不关心相关项排第 1 还是第 20 |
| MRR | 第一个相关 item 平均排多靠前 | 对第一命中位置敏感 |
| nDCG@10 | 分级相关项是否按 grade 排在前面 | 同时看次序与 1/2 级相关性 |

指标在 item 级去重后计算，避免一篇文章切出五个 chunk 占满前五名却看起来“召回很好”。

## 5. 生成评测怎样判断答案出口

生成变体会真实执行检索、重排和模型生成，再由确定性检查与审计字段评分：

| 指标 | 含义 |
|---|---|
| `citation_coverage` | 需要证据的事实句中，有多少带有效引用 |
| `citation_precision` | 引用落到黄金集相关 item 的比例；自动指标，不能替代人工支持度审核 |
| `story_coverage` | 该覆盖的相关事实/故事是否出现在答案里 |
| `support_mean` / `support_supported` | 引用 passage 与对应 claim 的支持度重排分数/达标率 |
| `must_contain_hit` | 必须出现的关键事实是否命中 |
| `refusal_rate_on_unanswerable` | 12 道不可答题是否正确拒答 |
| `over_refusal_rate` | 78 道可答题是否被错误拒绝 |
| `presupposition_asserted_rate` | 诱导题的错误前提是否被模型当真 |
| `forbidden_term_mentioned` | `must_not_claim` 禁止断言是否出现 |
| `latency_ms_mean` | 同一评测环境下的生成总延迟 |

服务端不会直接信任模型写的 citation 编号。模型输出先做 schema 解析，再将 evidence id 与本轮候选/物理 chunk 做绑定，移除弱支持引用，重新校验断言；无法安全解析或证据不足时 fail closed，部分回答或拒答。

## 6. `/eval` 页面从哪里来，会不会一直刷新

页面读取版本化静态文件 `apps/web/src/data/eval-summary.json`。该文件由：

```bash
python scripts/build_eval_summary.py
```

从 `docs/status/eval/m4-rag-eval-*.json` 的指定 run 构建。打开/刷新浏览器不会重新跑 90 题，不会调用模型，也不会随在线用户问题改变。只有主动跑评测、人工检查输出、更新被采纳 run 并重新构建/发布 Web 后，质量页才变化。

这和 `/ops` 不同：`/ops` 查询近 30 天 `llm_usage`、`rag_query` 等生产记录，并用 Redis 缓存 30 秒；因此运行状态会随真实调用变化，但价格仍是“调用时保存的价目快照或历史 fallback”，不是供应商账单。

## 7. 当前发布门怎样计算

质量页的 release gate 当前检查：

| 门禁 | 当前历史发布快照 | 阈值 |
|---|---:|---:|
| 主集 Recall@20 | 89.94% | ≥ 85% |
| 事实句引用覆盖 | 98.81% | ≥ 95% |
| 段落支持达标率 | 93.44% | ≥ 90% |
| 可回答题误拒 | 0 / 78 | 必须为 0 |
| 不可答题误断言 | 0 / 12 | 必须为 0 |

这些是 2026-08-11 的版本化历史快照，必须连同样本量、模型、配置与运行环境引用；不是 2026-08-15 每一次线上回答的实时正确率。自动 citation precision 不能替代数字关系、实体限定和高风险事实的人工逐条核验。

## 8. B1 到 B13 为什么保留失败实验

| 轮次 | 改动 | 结果与工程判断 |
|---|---|---|
| B1 | 纯 bge-m3 dense baseline | 建立可比较起点，不能凭主观样例宣布检索好 |
| B2 | 加 PostgreSQL sparse 后轮转交错合并 | Recall/MRR 反而下降；稀疏通道不是“加了必好”，必须有融合策略 |
| B3 | RRF + 时间过滤 | recent_updates 变好但多类 MRR 下滑；证明需要 reranker |
| B4 | bge-reranker-v2-m3 重排前 40 | 明显提升并被采纳；100 候选没有足够收益，不扩大成本 |
| B7 | freshness-aware 重排 | MRR 改善，避免最新问题被旧高相关文档压住 |
| B8 | 扫 42 组 dense/sparse/temporal 权重 | 最佳候选与现网只差约 0.0004，结论“不改”；没有为调参而上线调参 |
| B9/B10/B12 | directness、source fit、entity/subject/report、自适应深度 | 小幅可验证收益；按问题类型控制 rerank 深度 |
| B13 | PostgreSQL `simple` + CJK bigram | 中文分词端到端变化约 ±0.0000；保留实现收益的真实边界，不包装成指标飞跃 |
| GEN → GEN-FIX | 生成误拒定位与复测 | 发现模型有时返回完整 Markdown 而非 JSON，或只把编号写进 `claims[].evidence_ids`；出口容错并再次强校验后，误拒 7.69% → 0% |

GEN-FIX 最有价值的结论是：看起来像检索失败的问题，根因可能在生成响应解析与引用出口。若没有保存原始模型响应、逐题 run 和失败分支，只看最终空答案会误调检索参数。

## 9. 如何复跑和更新质量页

在服务依赖齐全、持有相应 provider key 的环境中：

```bash
# 先只校验黄金集和数据库引用
docker compose -f infra/compose/docker-compose.yml exec ai-service \
  python -m ahr.cli rag-eval --golden /app/data/golden --validate

# 检索基线/当前配置；output 要使用新的 run 文件名，不能覆盖历史证据
docker compose -f infra/compose/docker-compose.yml exec ai-service \
  python -m ahr.cli rag-eval --golden /app/data/golden \
  --variant b9-dimensions --output /app/docs/status/eval/<new-run>.json

# 生成侧会真实消耗模型额度
docker compose -f infra/compose/docker-compose.yml exec ai-service \
  python -m ahr.cli rag-eval --golden /app/data/golden \
  --variant generation --output /app/docs/status/eval/<new-generation-run>.json

# 确认要采纳哪些 run 后再构建前端摘要
python scripts/build_eval_summary.py
```

具体 variant 及参数始终以 `python -m ahr.cli rag-eval --help` 为准。每次实验输出必须包含 run id、golden 文件、语料快照、检索深度/权重、embedding/reranker/generation 模型、prompt/配置版本和逐题结果；不能只提交一行平均数。

## 10. 人工审核到底审核什么

本项目不把整站内容逐条人工编辑，也不把主题地图未经完整双人裁决的规则命中数说成 precision。RAG 的高风险人工审核针对固定题和发布候选：

1. 打开题目对应的原始 `content_revision.body_text`；
2. 核对 relevant item 是否直接/间接支持问题，grade 是否合理；
3. 核对生成答案每个事实 claim 的 citation 是否落到真正支持它的 passage；
4. 检查数字、单位、时间、实体限定与否定词；
5. 对不可答题确认答案没有顺从问题的错误前提；
6. 将结论、reviewer、run id 和原文证据写入版本化 status artifact。

这是一道发布门的人工抽查，不会在每个线上请求中同步阻塞用户。切换生成模型、prompt、切块或核心检索配置后必须重新跑相关门禁，不能沿用旧模型的结论。

## 11. 面试深挖问答

**问：90 道题是不是模型自己生成、自己评分？**

答：题与相关 item 是固定 YAML 标注，原始证据必须在 revision 正文中验证。检索指标确定性计算；生成有自动引用/支持/拒答检查，高风险样本仍人工对原文。模型不能用自己的摘要当裁判证据。

**问：为什么 `/eval` 不是实时？**

答：实时跑 90 题成本高、结果会被供应商波动污染，也无法复现。质量页展示经采纳、版本化 run；在线运行事实在 `/ops`。二者一个回答“这版算法过门了吗”，一个回答“生产最近运行怎样”。

**问：Recall 高是否说明回答一定正确？**

答：不说明。Recall 只证明相关 item 进候选；还要看 rerank 位置、claim-citation 支持、引用覆盖、错误前提、误拒答，并对数字与限定词人工核验。

**问：为什么保留 B2/B8 这种失败结果？**

答：它们证明技术选择是按同一黄金集做的，而不是功能堆叠。B2 说明稀疏通道需要正确融合，B8 说明大规模扫权重没有足够增益，所以不为“有调参”修改线上配置。

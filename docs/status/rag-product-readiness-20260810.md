# RAG 产品成熟度复核（2026-08-10）

本文是当前 checkout 的产品级复核，不替代锁定规格：规格仍以
`docs/spec/04-rag-agent-design.md` 与 `docs/spec/07-quality-security-ops.md` 为准。
本文回答三个问题：现在真正上线的 RAG 是什么、与成熟产品差在哪里、下一步按什么顺序做。

## 1. 结论先行

当前系统已经不是「向量库 + Prompt」演示，而是一个**合格的垂直领域、预生产阶段 RAG**：
有真实全文采集、时间/实体感知混合检索、交叉编码器重排、服务端引用绑定、支持度门控、
拒答、多轮对话、逐候选轨迹、90 题回归、成本/延迟与缓存观测。

它还不能称为完整成熟的企业级 RAG 产品。主要差距不在再加一种向量数据库，而在：

1. 权限与治理尚不完整（匿名公共问答、无租户/文档 ACL、缺输入输出安全策略）；
2. 发布工作流未闭环（14 份报告均为 DRAFT，现已阻止公共 API 暴露，但缺人工发布端点/UI）；
3. 评测仍缺噪声敏感性、中文厂商名→产品名专项集、持续回归和人工 P0 核验；
4. 候选集没有完整快照，`rag_query_id` 只能复现计划、证据与结果，不能严格重放当时候选序；
5. 供应商重排延迟有长尾，本次两次 90 题 B9 实跑分别在 120 秒、600 秒超时；
6. Source/Story 层向量与 Graph-lite 尚未实现，但现有数据不支持把它们排在上述缺口之前。

综合判断：**检索与证据链约 4/5，产品化约 3/5，企业治理约 2/5；整体 3.3/5。**
这是工程成熟度判断，不是把异质维度相加出来的精确分数。

## 2. 当前完整链路

```text
140 个注册信源
  → 发现页/RSS/API 只负责发现
  → HTML / GitHub / Changelog / arXiv HTML→PDF 回源全文
  → raw_document 审计原始响应
  → content_item / revision / chunk
  → bge-m3 向量 + PostgreSQL tsvector/GIN
  → Planner：类型、绝对时间窗、实体与厂商别名、追问改写
  → dense(60) + sparse(40) + temporal / entity_temporal
  → weighted RRF + 规格 §6 元数据调整
  → bge-reranker-v2-m3 重排
  → 每文档/每来源上限 + Story 折叠 + 父块阶梯
  → DeepSeek 生成（LLM 输出先按不可信处理）
  → 服务端反查引用 + 四条不变量
  → (论断 × 证据) 支持度门控，不足则移除或明确拒答
  → rag_query / rag_citation / rag_trace + Redis freshness-aware cache
  → /ask：计划、检索截至、证据概览、引用、来源等级、轨迹、降级态
```

### 2.1 语料与采集

- 注册信源 140，当前 ACTIVE 109；内容 1750，分块 6780，全部已有向量。
- RSS/Search snippet 从不算全文；原始响应、最终 URL、响应头、正文与提取器均可审计。
- arXiv 已按规范改为 `/html/{id}` 优先、`/pdf/{id}` 兜底，PDF 有页数和字符上限。
  真实 canary `2608.06394` 取得 234688 bytes、46787 正文字符。

### 2.2 查询理解与检索

- 正则 Planner 把「最近一周」冻结成绝对区间；LLM Planner 已实现但默认关闭，
  因为分类更准并未证明端到端更好，且会新增一次模型往返。
- dense 解决语义改写，sparse 解决型号/版本号；时间窗同时作为 dense/sparse 硬过滤。
- 一般时间问题增加 `temporal`；能解析出厂商实体的问题增加 subject 限定的
  `entity_temporal`。后者使用 1.0 权重，且在来源限流时保留实体命中，避免强相关条目
  被同来源的普通候选挤掉。
- 融合采用 RRF，不直接相加 cosine 与稀疏分数；B2 已实证简单并集全面退化。

### 2.3 重排、证据与生成

- 交叉编码器重排后再施加 directness/source_fit/temporal_fit 等受控维度；
  每文档、每来源上限和 Story 折叠控制重复与单一发布方垄断。
- 模型只看到被选中的原始证据父块；生成 JSON/正文均需解析，模型写的引用编号不能直接下发。
- 引用由服务端绑定真实 item 与段落；低于 0.30 的支持度引用被移除并重编号。
- 拒答不是 500，也不缓存；页面同时展示系统看过但不足以支撑回答的内容。

### 2.4 可观测与体验

- 每个候选记录 dense/sparse/temporal 通道、融合/重排名次、boost 与淘汰原因。
- 记录外部调用 token、成本、阶段耗时、降级通道和缓存命中。
- Redis 只省外部往返，不做事实源；答案键绑定问题、prompt、流水线版本和语料指纹。
- UI 保持原布局，新补「检索截至」与证据概览（引用数、发布方、支持度、一手来源）；
  Chrome 桌面/窄屏实测无应用控制台错误、无横向溢出，引用定位可交互。

## 3. 当前实测证据

### 3.1 检索

90 题黄金集（六类各 15；可答题 78、不可答题 12）：

| 轮次 | Recall@10 | Recall@20 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|
| B15（带完整重排的最近稳定基线） | 0.8509 | 0.8908 | 0.8720 | 0.8148 |
| ENTITY（本次通道/多样性诊断，B3 无重排） | 0.8071 | 0.8870 | 0.6357 | 0.6303 |

ENTITY 不能与 B15 横向宣布退化：它刻意不调用重排器，用来隔离检索通道行为。
它新增并实测：`distinct_sources@10=5.59`、`dominant_source_share@10=0.4397`、
`primary_source@5=0.5897`。相对同配置修复前，Recall@10 +0.0310、
`recent_updates` Recall@10 0.6600→0.8044。

真实回归题「最近七天里，智谱发布了什么？」此前错误拒答；修复后：

- 时间范围正确解析为 2026-08-03 至 2026-08-10；
- 通道为 dense 60 / sparse 40 / entity_temporal 2；
- GLM-5.2 目标内容进入最终证据并生成回答；
- 引用支持度 0.9550，未拒答。

### 3.2 生成与引用

最新双口径生成评测：citation coverage 0.8880、citation precision 0.5487；
段落级支持度均值 0.8429、达标率 0.9371；模型实际读取父块口径均值 0.9065、
达标率 1.0000；可答题误拒率 0，断言假前提率 0。

这里最重要的事实不是「1.0000」，而是父块支持度已参与门控，因此它是门控结果、
不是独立测量。产品判据使用仍能失败的段落级 0.9371（ADR-0021）。

### 3.3 工程门禁

- Python：827 passed；Ruff check 全绿；mypy 84 个源码文件全绿。
- Web：54 passed；ESLint、TypeScript、Next.js production build 全绿。
- Java：Java 21 容器内 55 passed。
- Ruff 全库 format 尚有 19 个未触及的历史文件会被新版格式器重排；未混入本次功能提交。

## 4. 成熟 RAG 产品通常具备什么

成熟产品不是单一算法，而是一套可运行、可治理、可评测的知识系统：

| 能力层 | 成熟产品的常见形态 | 本项目 |
|---|---|---|
| 数据接入 | 多连接器、增量同步、解析/OCR、版本、失败重放、权限元数据 | 公共 AI 信源做得较完整；无企业 SaaS 连接器/OCR/ACL |
| 索引 | 文本+向量+结构化元数据，多粒度 chunk，增量更新与删除传播 | 已有文本/向量/时间/实体；Story 向量未做 |
| 查询 | 意图、改写/拆解、混合召回、元数据过滤、多查询融合 | 已有规划、别名、时间/实体过滤、RRF；通用改写默认关闭 |
| 排序 | reranker、业务规则、来源多样性、可解释分数 | 已有，且记录逐候选轨迹 |
| 生成 | 结构化输出、引用、拒答、grounding/安全校验 | 已有引用/支持度/拒答；安全策略与提示注入防护不足 |
| 评测 | 黄金集、检索/生成/延迟/成本、回归门禁、线上反馈闭环 | 离线较强；持续评测、噪声集、人工 P0 与用户反馈闭环不足 |
| 治理 | RBAC/ACL、租户隔离、审计、PII、保留/删除、发布审批 | 管理 token 与审计已有；公共问答无 ACL/租户，发布未闭环 |
| 运行 | 超时、重试、限流、缓存、熔断、SLO、告警、灾备 | 基础具备；供应商长尾、告警与恢复演练未闭环 |

公开厂商方案也体现了相同方向：Azure 把 hybrid（全文+向量）、RRF、semantic rerank、
query rewrite 与引用详情作为组合能力；AWS Knowledge Bases 提供元数据过滤、rerank、
直接引文/自然语言回答，并把 contextual grounding、PII 与 prompt-attack 检测放进 Guardrails；
Elastic 的官方范例同样用 lexical + semantic + RRF，而不是只做向量 top-k。

官方参考：

- https://learn.microsoft.com/azure/search/retrieval-augmented-generation-overview
- https://learn.microsoft.com/azure/search/semantic-search-overview
- https://docs.aws.amazon.com/bedrock/latest/userguide/kb-how-it-works.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/rerank.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
- https://www.elastic.co/guide/en/elasticsearch/reference/8.19/semantic-text-hybrid-search.html

## 5. 优化顺序

### P0：上线前必须完成

1. 实现报告人工发布端点/UI 与审计；公共 API 已 fail-closed，只读 `PUBLISHED`。
2. 轮换全部密钥、设置供应商消费上限、完成一次真实备份恢复演练。
3. 给公开问答补输入安全策略、prompt injection/敏感信息基线；若引入账户，再做行级 ACL。
4. 对关键问答做人工引用 P0 核验，不能用自动支持度代理人工判定。

### P1：直接提高 RAG 质量

1. 黄金集新增至少 15 道「中文厂商名→英文产品/模型名」题和带噪上下文对照集。
2. 在同一进程、同一候选快照里跑 entity_temporal 的带重排 A/B，隔离 HNSW 漂移。
3. 给 `rag_query_id` 保存候选 ID/顺序/模型版本摘要，使历史回答可严格重放。
4. 对 citation completeness 0.888 与段落支持度 0.937 的交易做逐题人工分析，
   不通过调低支持阈值把表格刷绿。
5. 只有当专项题证明召回缺口后，再评测 dense 查询改写或多查询；不默认增加一次 LLM 往返。

### P2：规模与运行成熟度

1. 为 embedding/rerank/generate 分别建立供应商超时率与 p95/p99 SLO，增加熔断/备用模型策略。
2. 将离线回归放入定时/发布流水线，分离免费检索回归与有预算上限的生成回归。
3. 补线上显式反馈（引用有用/无关/过期）及回标流程，避免只优化离线黄金集。
4. 当 Story 多信源样本足够后再评估 Story 向量；Graph-lite、ES、Kafka、Kubernetes
   仍需有实测触发条件，不因「成熟产品常见」而引入。

## 6. 与本次发布链路审计的关系

数据库当前有 14 份报告，全部为 DRAFT；公共报告 API 现已只返回 PUBLISHED，
因此当前 `/reports` 为空是正确的 fail-closed 行为，不应把草稿自动发布来换页面有内容。
Outbox 当前 1807 条未消费事件（最早 2026-08-01），没有真实下游消费者；正确性由
业务状态重开 PENDING + poller 保证。没有真实异步下游前，不实现只会“标记已消费”的空消费者。


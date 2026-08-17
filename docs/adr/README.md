# 架构决策记录（ADR）索引

ADR 只回答“为什么这样选、否决了什么、什么证据会触发回滚”，不承担实时状态记录。
当前运行事实见 [`../status/current/`](../status/current/README.md)，实现细节见
[`../handbook/`](../handbook/README.md)。

## 两层编号为什么同时存在

总规格中的 `ADR-001`～`ADR-011` 是项目建立时锁定的一级决策，正文集中保存在
[`../spec/00-master-spec.md`](../spec/00-master-spec.md#3-不可更改的架构决策adr)。它们没有各自的
独立文件，并不是文件丢失：

| 总规格决策 | 核心结论 |
|---|---|
| ADR-001～003 | Next.js Web、Spring Boot Core API、Python FastAPI AI Service 的服务边界 |
| ADR-004～005 | PostgreSQL/pgvector 是唯一事实源；Redis 只做缓存、限流和短状态 |
| ADR-006～007 | 模块化单体 + 独立 AI worker；当前任务编排用 PostgreSQL 租约轮询 |
| ADR-008～010 | 时间/事件感知混合 RAG、原文 evidence 引用、PostgreSQL graph-lite |
| ADR-011 | 发现与全文获取分离，公开展示受版权和正文门约束 |

`0012-*` 起是开发中遇到具体问题后新增的独立 ADR。文件名前缀保持四位，便于按时间排序；
其中 0028、0029 分别把总规格 ADR-007、ADR-009 的“当前物理实现”说得更精确。

## 独立 ADR 分组

| 主题 | ADR |
|---|---|
| 信源、实体与正文 | [0012](0012-source-schema-discovery-url-conditional.md)、[0013](0013-openai-cdn-blocks-non-browser-clients.md)、[0014](0014-entity-types-align-to-taxonomy.md) |
| 混合检索与缓存 | [0015](0015-rag-sparse-channel-uses-postgres.md)～[0018](0018-cjk-bigrams-in-postgres-not-a-segmenter.md) |
| 管理认证与评测语义 | [0019](0019-admin-auth-is-a-bearer-token-not-spring-security.md)～[0023](0023-high-risk-numeric-relations-use-controlled-llm-audit.md) |
| RAG 安全、报告和模型配置 | [0024](0024-rag-prompt-safety-and-provider-fail-fast.md)～[0027](0027-deepseek-generation-model-selection-is-database-backed.md) |
| 编排、证据、主题关系与索引版本 | [0028](0028-current-task-orchestration-is-database-polling.md)～[0031](0031-content-chunk-sets-are-versioned.md) |

## 维护规则

1. 数据库/队列/搜索引擎、服务边界、认证、RAG 检索策略、核心实体或破坏性 API 改动，先写 ADR 再改代码。
2. ADR 记录当时上下文和证据；决策被替代时新增 ADR 并标注 supersedes，不重写历史。
3. “以后也许会上 Kafka/Kubernetes/独立向量库”不是决策。必须先出现容量、可靠性或团队协作证据。
4. ADR 中出现的测试数字是决策时快照；引用时必须带日期、样本量、模型和环境。


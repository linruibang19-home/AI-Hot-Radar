# 文档导航

本目录按用途分为六类：`spec/` 是锁定契约，`adr/` 记录偏离契约的决策，
`design/` 是随开发修订的实现方案，`status/` 是实际运行产生的事实，
`handbook/` 是完整工程教材，`interview/` 把已经实现的事实训练成复习与答辩表达。

## `handbook/` — 完整工程教材

[工程手册入口](handbook/README.md) 从产品问题、四条业务链路、运行服务、数据状态、信源、
内容、报告邮件一路讲到 RAG、Java/Python/Next、部署和工程权衡。它回答“系统怎样工作、代码
在哪里、为什么这样做、失败如何恢复”，是吃透项目的第一入口。

## `spec/` — 工程规格（唯一事实源）

产品、架构、数据、接口、采集、RAG、前端、安全与路线图的锁定规格。发生冲突时以
`spec/00-master-spec.md` 的锁定决策优先。

| 文件 | 作用 |
|---|---|
| [00-master-spec.md](spec/00-master-spec.md) | 总规格与 ADR-001~011 锁定决策 |
| [01-product-requirements.md](spec/01-product-requirements.md) | 页面、角色与产品验收 |
| [02-system-architecture.md](spec/02-system-architecture.md) | 服务边界、状态机、部署 |
| [03-data-ingestion.md](spec/03-data-ingestion.md) | 数据模型、去重、切块、Story |
| [04-rag-agent-design.md](spec/04-rag-agent-design.md) | 时间与事件感知 RAG |
| [05-api-contract.md](spec/05-api-contract.md) | HTTP 与任务契约 |
| [06-frontend-spec.md](spec/06-frontend-spec.md) | 路由、页面、组件状态 |
| [07-quality-security-ops.md](spec/07-quality-security-ops.md) | 测试、安全、版权、运维 |
| [08-roadmap-ai-ide.md](spec/08-roadmap-ai-ide.md) | M0–M5 里程碑与任务卡 |
| [09-source-registry-fulltext.md](spec/09-source-registry-fulltext.md) | 信源分层与全文标准 |
| [10-source-adapter-implementation.md](spec/10-source-adapter-implementation.md) | 各类接口读取与字段映射 |
| [11-end-to-end-runbook.md](spec/11-end-to-end-runbook.md) | 联调与恢复流程 |
| [12-delivery-index.md](spec/12-delivery-index.md) | 交付索引 |

## `code-map.md` — 代码学习入口

[代码全景与学习地图](code-map.md) 按“采集到页面、报告与邮件、RAG、管理权限、发布与测试”
组织全部实现文件。它用于回答代码在哪里，不替代规格和 ADR。

## `adr/` — 架构决策记录

偏离或补充规格的决策都必须先有 ADR。格式：背景、决策、备选、后果、回滚。

| 编号 | 决策 |
|---|---|
| [0012](adr/0012-source-schema-discovery-url-conditional.md) | `discovery_url` 改为按 profile 条件必填 |
| [0013](adr/0013-openai-cdn-blocks-non-browser-clients.md) | OpenAI 官网回源被 CDN 拒绝，降级 metadata_only |
| [0014](adr/0014-entity-types-align-to-taxonomy.md) | 实体类型以 `config/taxonomy.yaml` 的 8 类为准 |
| [0015](adr/0015-rag-sparse-channel-uses-postgres.md) | 稀疏检索复用 Postgres 既有索引，不引入 ES / Neo4j |
| [0016](adr/0016-rag-adaptive-parent-block.md) | 父块自适应阶梯，由查询派生而非物化落表 |
| [0017–0027](adr/) | 缓存、CJK、鉴权、拒答、引用、迁移、数字审计、发布、订阅与模型配置 |
| [0028](adr/0028-current-task-orchestration-is-database-polling.md) | 当前后台编排是 PostgreSQL 轮询，Outbox 未消费 |
| [0029](adr/0029-evidence-passage-is-the-content-chunk-physical-row.md) | evidence passage 的当前物理行是 `content_chunk` |

## `design/` — 开发方案（活文档）

规格没有规定、但实现必须定下来的做法，以及开发中因实测发现而做的方案调整。
每份文档都有「变更记录」小节，记录方案因何被修正。

| 文件 | 范围 |
|---|---|
| [design/README.md](design/README.md) | 四层文档的分工与写入规则 |
| [m4-rag-implementation.md](design/m4-rag-implementation.md) | M4 RAG 全流程实现方案与外部方案取舍 |
| [m4-rag-evaluation.md](design/m4-rag-evaluation.md) | 90 题黄金集、指标含义与发布门禁 |
| [m5-deployment.md](design/m5-deployment.md) | 单机生产部署、安全与恢复设计 |
| [m5-first-deploy-checklist.md](design/m5-first-deploy-checklist.md) | 首次部署逐步检查表与危险操作边界 |

## `status/` — 运行状态与验收证据

由实际运行生成，随开发进度更新。

| 文件 | 内容 |
|---|---|
| [status/README.md](status/README.md) | **状态总索引**：当前入口、历史快照、RAG 与发布证据 |
| [project-status.md](status/project-status.md) | **项目总进度**：里程碑、数据、信源、服务、待办 |
| [m1-canary-evidence.md](status/m1-canary-evidence.md) | M1 信源探测验收证据 |
| [m1-canary-evidence.json](status/m1-canary-evidence.json) | 逐源原始数据 |
| [rag-product-readiness-20260810.md](status/rag-product-readiness-20260810.md) | **当前 RAG 全链路、成熟产品对标与优化顺序** |
| [handoff-20260812.md](status/handoff-20260812.md) | 当前生产、提交、数据与下一步入口 |
| [repository-hygiene-20260812.md](status/repository-hygiene-20260812.md) | 本轮全仓盘点、清理与可恢复归档证据 |

`handoff-20260810.md` 与 `handoff-20260811.md` 是历史快照，不用来判断当前运行版本。

## 其他入口

- [../README.md](../README.md) — 项目总入口与规范优先级
- [../DEVELOPMENT.md](../DEVELOPMENT.md) — 本地开发、启动、常见问题
- [interview/README.md](interview/README.md) — 面试准备导航、系统地图、题库与演示脚本
- [interview-guide.md](interview-guide.md) — 2026-08-12 冻结的早期深挖稿；新材料已迁入 handbook/interview
- [archive-policy.md](archive-policy.md) — 文档状态、冻结与归档规则

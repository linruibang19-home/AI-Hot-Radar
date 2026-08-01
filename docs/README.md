# 文档导航

本目录按用途分为三类。

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

## `adr/` — 架构决策记录

偏离或补充规格的决策都必须先有 ADR。格式：背景、决策、备选、后果、回滚。

| 编号 | 决策 |
|---|---|
| [0012](adr/0012-source-schema-discovery-url-conditional.md) | `discovery_url` 改为按 profile 条件必填 |
| [0013](adr/0013-openai-cdn-blocks-non-browser-clients.md) | OpenAI 官网回源被 CDN 拒绝，降级 metadata_only |

## `status/` — 运行状态与验收证据

由实际运行生成，随开发进度更新。

| 文件 | 内容 |
|---|---|
| [project-status.md](status/project-status.md) | **项目总进度**：里程碑、数据、信源、服务、待办 |
| [m1-canary-evidence.md](status/m1-canary-evidence.md) | M1 信源探测验收证据 |
| [m1-canary-evidence.json](status/m1-canary-evidence.json) | 逐源原始数据 |

## 其他入口

- [../README.md](../README.md) — 项目总入口与规范优先级
- [../DEVELOPMENT.md](../DEVELOPMENT.md) — 本地开发、启动、常见问题

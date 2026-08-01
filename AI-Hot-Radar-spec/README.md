# AI Hot Radar 工程规格书

> 版本：v1.2.0  
> 状态：可进入开发  
> 基线日期：2026-08-01  
> 适用执行器：Codex、Claude Code、Cursor 及人工开发者

AI Hot Radar 是一个面向 AI 行业的时效性情报平台。系统统一采集国内外公开信源，完成清洗、去重、结构化、事件聚合、精选评分和报告生成，并提供带时间范围、事件去重和来源引用的 RAG Agent。

## 文档导航

| 文件 | 作用 | 开发前是否必读 |
|---|---|---|
| `docs/00-master-spec.md` | 唯一总规格与决策基线 | 是 |
| `docs/01-product-requirements.md` | 产品范围、页面与验收 | 是 |
| `docs/02-system-architecture.md` | 服务边界、数据流与部署 | 是 |
| `docs/03-data-ingestion.md` | 数据模型、采集和事件聚合 | 涉及后端/数据时必读 |
| `docs/04-rag-agent-design.md` | 时间与事件感知 RAG | 涉及 AI/RAG 时必读 |
| `docs/05-api-contract.md` | HTTP 与内部任务契约 | 涉及接口时必读 |
| `docs/06-frontend-spec.md` | 路由、页面、组件和状态 | 涉及前端时必读 |
| `docs/07-quality-security-ops.md` | 测试、安全、版权和运维 | 上线前必读 |
| `docs/08-roadmap-ai-ide.md` | 里程碑、任务卡和 AI IDE 规则 | 是 |
| `docs/09-source-registry-fulltext.md` | 140 个信源、全文回源、状态机与验收 | 采集开发必读 |
| `docs/10-source-adapter-implementation.md` | 各类接口怎样读取、字段映射、游标和代码边界 | 采集开发必读 |
| `docs/11-end-to-end-runbook.md` | 从定时触发到网站、邮件、RAG 的完整运行链路 | 联调/运维必读 |
| `docs/12-delivery-index.md` | 全部文件、用途、完成度和执行顺序 | 是 |
| `config/sources.yaml` | 140 个可执行采集入口 | 采集开发必读 |
| `config/social-watchlist.yaml` | 30 个 X 与 8 个公众号受限监控目标 | 社交适配器开发必读 |
| `config/taxonomy.yaml` | 分类、实体和内容类型 | 内容加工必读 |
| `config/ingestion-profiles.yaml` | 9 类采集 Profile 的机器可读执行契约 | 采集开发必读 |
| `config/site-overrides.yaml` | 特殊站点覆盖、候选 selector 与启用门禁 | 站点适配必读 |
| `database/V001__baseline.sql` | PostgreSQL/pgvector 基线模型 | 后端必读 |
| `api/openapi.yaml` | 公共、RAG 与管理 API 基线 | 前后端必读 |
| `schemas/*.json` | Source 与任务事件契约 | 后端/Worker 必读 |

## 规范优先级

发生冲突时按以下顺序处理：

1. `docs/00-master-spec.md` 中的锁定决策；
2. 领域专项文档；
3. `config/*.yaml` 机器可读配置；
4. AI IDE 自己生成的计划或实现建议。

任何执行器不得静默改变技术栈、核心实体、API 语义和里程碑边界。确需改变时，先新增 ADR，再修改文档与代码。

## 规范词

- **MUST / 必须**：验收硬条件；
- **SHOULD / 应当**：默认执行，偏离需记录原因；
- **MAY / 可以**：可选增强；
- **OUT**：当前版本明确不做。

## 一句话开发策略

先打通“真实信源 → 可追溯内容 → 事件 → 网站/日报”，再加入“时间化混合检索 → 证据选择 → 引用回答”；不在 MVP 阶段堆叠重型 GraphRAG、RAPTOR、OCR 和微服务。

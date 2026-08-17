# 12｜交付与证据索引

文档 ID：`AHR-INDEX-1200`

版本：`v1.5.0`

更新时间：2026-08-17

本页回答“仓库交付了什么、证据放在哪里”，不复制易变化的生产数字。当前线上版本、
镜像、迁移、容器和数据量只以
[`docs/status/current/production-baseline.md`](../status/current/production-baseline.md)
为准；历史验收只说明当时发生过什么，不能替代当前状态。

## 1. 四类入口

| 需要了解什么 | 首选入口 | 事实性质 |
|---|---|---|
| 项目定位、架构与快速体验 | [`README.md`](../../README.md) | 稳定说明 + 带日期快照 |
| 当前生产事实 | [`status/current/README.md`](../status/current/README.md) | 唯一 current 入口 |
| 从业务到实现系统学习 | [`handbook/README.md`](../handbook/README.md) | 当前实现教材 |
| 面试表达、追问和代码走读 | [`interview/README.md`](../interview/README.md) | 基于实现的训练材料 |
| 锁定需求与架构边界 | [`00-master-spec.md`](00-master-spec.md) + [`adr/`](../adr/README.md) | 规范/决策 |
| 当前任务与完成历史 | [`08-roadmap-ai-ide.md`](08-roadmap-ai-ide.md) | 任务卡台账 |
| 部署、备份、恢复与迁移 | [`status/operations/`](../status/operations/) | 带日期运维证据 |
| RAG 实验和发布门 | [`status/eval/`](../status/eval/) | 固定 run 证据 |

## 2. 可执行交付物

| 路径 | 交付物 | 负责范围 |
|---|---|---|
| `apps/web/` | Next.js 网站 | SSR 页面、交互、同源代理、RAG 流式 UI |
| `apps/core-api/` | Spring Boot Core API | 公共读 API、报告/订阅、管理 RBAC 与审计 |
| `apps/ai-service/` | FastAPI AI Service + worker | 采集、正文抽取、结构化、聚类、报告生成、RAG 与评测 |
| `database/migrations/` | Flyway 迁移链 | PostgreSQL/pgvector 的唯一结构演进历史，禁止删除或压平 |
| `api/` + `schemas/` | 跨服务契约 | OpenAPI、JSON Schema 与生成类型输入 |
| `config/` | 运行策略 | 信源注册、采集 Profile、主题词表与模型白名单 |
| `data/golden/` | 固定评测输入 | 90 题黄金集、fixture 和可复现实验数据；不放生产秘密 |
| `infra/compose/` | 本地/生产编排 | PostgreSQL、Redis、三服务、worker、Caddy 与运维容器 |
| `infra/scripts/` | 生产脚本 | 预检、部署、smoke、备份、隔离恢复与监控 |
| `.github/workflows/` | CI/CD | 分层验证、镜像构建、GHCR 发布与发布门 |

公开产品路由包括 `/`、`/items`、`/hot`、`/stories`、`/topics`、`/reports`、
`/ask`；工程观测路由包括 `/eval`、`/ops`、`/admin/models`、`/admin/sources`。
这些页面读取同一份 PostgreSQL 已发布事实，但 `/eval` 展示固定评测快照，不能当实时监控。

## 3. 核心业务交付

```text
公开信源
  -> 发现元数据
  -> 回源抓取正文 + 全文质量门
  -> item / revision（原始证据与版本）
  -> LLM 结构化（不覆盖原文）
  -> 去重 / story 聚类 / 精选评分
  -> 精选、热点、主题、事件、日周月报
  -> 双确认邮件订阅（只发送 PUBLISHED 报告快照）

同一 revision 正文
  -> 结构感知切块
  -> bge-m3 embedding + pgvector
  -> dense / sparse / temporal 候选
  -> 融合 + bge-reranker-v2-m3
  -> DeepSeek 生成
  -> 服务端绑定句级引用与原文 URL
  -> 支持不足时部分回答或拒答
```

交付边界：RSS 摘要只用于发现；RAG 最终证据只能来自原始 evidence chunk；Redis
不保存唯一业务事实；邮件不在发送时临时生成报告；模型输出通过 schema 和引用门后才可发布。

## 4. 质量与可恢复性证据

| 主张 | 如何核验 |
|---|---|
| 三端代码可构建 | Python pytest/mypy/Ruff、Web typecheck/lint/test/build、Java Maven verify |
| 空库可升级 | CI 从空 PostgreSQL 执行完整 Flyway 链 |
| 契约未漂移 | OpenAPI/Schema 生成后必须无 diff |
| RAG 不是主观演示 | 90 题固定黄金集、逐题 artifact、检索/生成/延迟分层指标 |
| 负实验被保留 | B2、B8、B13、GEN 与 GEN-FIX 的输入、判断和回滚证据 |
| 发布可定位 | Git commit、不可变 `sha-<commit>` 镜像与生产 `IMAGE_TAG` 分开记录 |
| 数据可恢复 | 备份目录校验、SHA-256、隔离数据库恢复和恢复后 smoke |
| 管理操作可追责 | OPERATOR RBAC、二次确认、幂等键与审计记录 |

任何指标都必须同时带日期、样本量、模型/配置版本和测量环境。当前数字见生产基线；
历史 run 见 `docs/status/eval/`，两者不得混用。

## 5. 文档层级

| 目录 | 回答的问题 | 是否允许记录动态数字 |
|---|---|---|
| `docs/spec/` | 产品和架构必须是什么 | 原则上否；任务状态除外 |
| `docs/adr/` | 为什么这样选、何时回滚 | 只记录决策当时证据 |
| `docs/handbook/` | 当前代码实际上怎样工作 | 少量稳定常量；动态事实链接 current |
| `docs/interview/` | 怎样基于代码讲清楚并应对追问 | 可引用，但必须标日期和环境 |
| `docs/status/current/` | 现在部署的是什么 | 是；必须标 `as of` |
| `docs/status/{product,operations,eval,delivery,history}/` | 某次验收或实验发生了什么 | 是；冻结后不追改历史结论 |
| `docs/design/` | 某项实现前后的设计证据 | 需标 current 或 historical |

## 6. 维护规则

1. 当前事实只更新 `docs/status/current/production-baseline.md`，其他入口链接它。
2. 版本发布后保留原验收文档，不把旧数字改成新数字伪装成当时结果。
3. 数据库、服务边界、认证、RAG 策略、核心实体或破坏性 API 改动先写 ADR。
4. migrations、schemas、CI 和 infra 是可验证交付的一部分，不能为缩短目录而删除。
5. 新工作只从 `08-roadmap-ai-ide.md` 领取一张任务卡；本索引不维护“下一阶段愿望清单”。

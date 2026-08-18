# AI Hot Radar 当前生产基线

> 截至：2026-08-19 CST（v0.1.20 部署后）。该快照不是实时承诺；动态状态以线上只读接口和目标机复核为准。

## 1. 代码与运行版本

| 项目 | 已核验事实 |
|---|---|
| 在线地址 | `https://aihotradar.online` |
| 生产业务版本 | `v0.1.20@0914ae9bef2ef2cc60d116ee0262d52ee63192cb` |
| 当前仓库 `main` | 可能包含生产后的文档提交；不能直接等同于生产镜像 |
| 主机 | 香港 Ubuntu 22.04.5，2C4G，40 GiB |
| 编排 | Docker Compose，10 个容器 |
| 公网入口 | Caddy 80/443；Core API、AI Service、PostgreSQL、Redis 不直接暴露公网 |
| 数据库 | PostgreSQL 16 + pgvector；生产与仓库同为 Flyway V027 |

三张业务镜像在发布时使用同一个不可变 `sha-<commit>` 标签。标准发布、回滚和 smoke 命令见
[`../../spec/11-end-to-end-runbook.md`](../../spec/11-end-to-end-runbook.md)。

## 2. 数据快照

2026-08-19 从香港生产 PostgreSQL 实查：

| 指标 | 数值 |
|---|---:|
| 登记信源 / 允许调度 / 运行态 ACTIVE | 143 / 131 / 110 |
| 内容 | 2816 |
| active chunk / 已向量化 | 12939 / 12939 |
| Story | 2322 |
| RAG 问答 / 引用 | 234 / 1003 |
| 报告 | 23 |

这些数字会随调度继续增长。网站、报告、邮件、RAG、订阅和审计的业务事实均来自 PostgreSQL；
Redis 只保存可重建缓存、限流计数、短锁、RAG 会话热副本和 30 秒运行统计快照。

## 3. 当前能力边界

- 公开列表只展示 `ENRICHED` 且中文标题、摘要完整的内容；原始正文仍保留在证据层；
- RAG 只引用原始 `content_chunk`，服务端绑定引用与 URL，证据不足时部分回答或拒答；
- `/eval` 是固定黄金集的版本化发布快照，不是实时监控；`/ops` 才读取运行数据；
- 报告邮件只投递 `PUBLISHED` 快照，不在发送时重新生成内容；
- 当前任务编排是 PostgreSQL 租约轮询，`outbox_event` 尚无消费者；
- 图片没有 OCR/视觉向量；arXiv PDF 只做受限文本抽取，不承诺版面级引用；
- 生成供应商地址与 API Key 可在 `/admin/models` 改，写库前先向供应商验证一次；
  未改动时该行是 `env://LLM_BASE_URL` 占位，三个生成侧容器逐字段回落到环境变量。
  只接官方兼容端点，不支持中转站（见 [ADR-0032](../../adr/0032-generation-provider-credentials-are-database-backed.md)）。

## 4. 生产验证证据

- v0.1.20 发布与部署验收：[`../delivery/ui-type-scale-release-20260819.md`](../delivery/ui-type-scale-release-20260819.md)；
- v0.1.19 发布与部署验收：[`../delivery/model-console-release-20260819.md`](../delivery/model-console-release-20260819.md)；
- 架构与业务流程通读核查：[`architecture-review-20260818.md`](architecture-review-20260818.md)；
- 当前交接与 v0.1.18 验收历史：[`handoff-20260814.md`](handoff-20260814.md)；
- 国内官方源和信源后台：[`../product/domestic-source-expansion-20260817.md`](../product/domestic-source-expansion-20260817.md)；
- 生产压测：[`../loadtest/2026-08-14-m5-020-production.md`](../loadtest/2026-08-14-m5-020-production.md)；
- 首次部署：[`../delivery/production-deployment-20260811.md`](../delivery/production-deployment-20260811.md)；
- RAG 发布门：[`../product/rag-specialist-audit-20260811.md`](../product/rag-specialist-audit-20260811.md)。

## 5. 当前任务

当前任务为 `TASK-M5-030`。任务状态只在
[`../../spec/08-roadmap-ai-ide.md`](../../spec/08-roadmap-ai-ide.md) 维护，不再复制到多份交接文档。

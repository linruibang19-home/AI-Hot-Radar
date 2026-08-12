# 代码全景与学习地图

本文档回答“一个用户动作最终走到哪些文件”。它是代码导航，不替代 `spec/`、ADR 或运行证据。
阅读代码时先从入口向下追，不建议按文件名从头背诵。

## 1. 仓库边界

| 区域 | 入口 | 事实边界 |
|---|---|---|
| Web | `apps/web/src/app/` | Next.js SSR 页面、同源代理与交互；不直接连接数据库 |
| Core API | `apps/core-api/src/main/java/` | 内容读取、报告发布、订阅、邮件、管理权限与审计 |
| AI Service | `apps/ai-service/src/ahr/` | 采集、加工、Story、报告生成、RAG 与评测 |
| PostgreSQL | `database/migrations/` | 唯一业务事实源；Flyway 只前进、不改历史迁移 |
| Redis | Java `cache/`、Python `rag/cache.py` | 缓存、配额与短状态；丢失后可由 PostgreSQL 恢复 |
| 契约与配置 | `api/`、`schemas/`、`config/` | HTTP、事件、信源、采集 Profile 和分类法 |
| 交付 | `infra/`、`.github/workflows/` | Compose、Caddy、备份、监控、CI 与不可变镜像发布 |

## 2. 从信源到页面

```text
config/sources.yaml + ingestion-profiles.yaml
  → ingestion/registry.py
  → ingestion/scheduler.py 分配租约
  → ingestion/adapters/* 发现候选
  → ingestion/http.py + ssrf.py 安全请求
  → article.py + fulltext_gate.py 回源和正文门
  → ingestion/repository.py 幂等写 content_item/revision
  → processing/worker.py + pipeline.py 领取加工任务
  → processing/llm.py + schemas.py 结构化模型输出
  → chunking.py / dedup.py / story.py / selection.py
  → Core API content/* 查询
  → Web app/page.tsx、items/*、stories/*、topics/*
```

重点阅读顺序：`ingestion/models.py` → `registry.py` → `pipeline.py` →
`processing/pipeline.py` → `database/migrations/V001..V012`。遇到具体 Adapter 再进入
`ingestion/adapters/`，不要先把七类适配器混在一起读。

## 3. 报告与邮件订阅

```text
processing/report.py 生成结构化日/周/月报
  → processing/email.py 发送内部候选通知
  → Core ReportPublicationService 执行发布状态机
  → report 表 PUBLISHED 快照
  → ReportController / Web reports/* 展示

Web ReportSubscribe
  → /api/subscriptions 同源代理
  → ReportSubscriptionController/Service
  → SubscriptionMailer 确认邮件
  → 用户确认后 ACTIVE
  → ReportEmailDeliveryService 定时领取到期报告
  → SubscriptionMailer SMTP 投递 + email_delivery 幂等记录
```

核心文件：Python `processing/report.py`；Java `admin/ReportPublicationService.java`、
`subscription/ReportSubscriptionService.java`、`ReportEmailDeliveryService.java`；Web
`ReportWorkspace.tsx`、`ReportSubscribe.tsx`。数据库状态在 V022–V023。

## 4. RAG 全链路

```text
Web AskPanel
  → /api/ask/route.ts
  → FastAPI rag/api.py
  → planner.py + llm_planner.py + conversation.py
  → embeddings.py
  → retrieval.py: dense / sparse / temporal / entity temporal
  → fusion.py + rerank.py + dimensions.py
  → folding.py + parent.py + context.py
  → answer.py 生成、绑定引用、过滤与不变量
  → support.py 支持度门
  → service.py 持久化 rag_query / rag_citation / trace
  → cache.py freshness-aware 缓存
  → AskPanel + RetrievalTrace 展示回答、引用和检索解释
```

建议按以下顺序学习：

1. `rag/planner.py`：问题如何成为带时间、实体与类型的计划；
2. `rag/retrieval.py`、`fusion.py`：召回与 RRF 为什么分开；
3. `rag/rerank.py`、`dimensions.py`：语义重排和受控元数据调整；
4. `rag/folding.py`、`parent.py`、`context.py`：去冗余与父块展开；
5. `rag/answer.py`、`support.py`、`safety.py`：模型输出为什么仍不可信；
6. `rag/service.py`：线上各步骤如何串联和留痕；
7. `rag/eval/` + `data/golden/`：检索、生成、拒答、延迟如何被固定数据验证；
8. `apps/web/src/components/AskPanel.tsx`：阶段事件、会话、引用和永久链接如何呈现。

对应迁移：V012 向量索引、V013 检索轨迹、V014 CJK bigram、V015 限制说明、V020 会话、
V021 历史答案修复。完整算法背景见 `docs/interview/03-rag-deep-dive.md` 和
`docs/design/m4-rag-implementation.md`。

## 5. 管理、权限与模型配置

Java `admin/` 是管理事实边界：`AdminAuthFilter` 认证，`AdminPrincipal/Role` 表达权限，
`AdminIdempotency` 防重复动作，`AdminAudit` 留审计。模型切换由
`GenerationModelController/Service` 写 PostgreSQL；Web `admin/models/` 只允许白名单型号，
不读取或显示密钥。信源页目前主要通过 `SourceHealthController` 读取数据库快照。

## 6. 运行与发布

- 本地唯一入口：`infra/compose/docker-compose.yml`；
- 生产入口：`docker-compose.prod.yml` + `preflight.sh` + `deploy-production.sh`；
- 公网唯一入口：`infra/caddy/Caddyfile`；
- 备份/恢复：`backup.sh`、`restore-verify.sh`；
- 监控/验收：`monitor.py`、`smoke-production.sh`；
- CI：`.github/workflows/ci.yml`；Release：`.github/workflows/release.yml`。

生产服务器不编译源码，只选择 GHCR 的不可变 `sha-<commit>` 镜像。GitHub `main` 可以比生产
运行版本多文档或未发布运维改动，因此判断线上代码必须同时看服务器 HEAD、`IMAGE_TAG` 和容器镜像。

## 7. 测试如何对应风险

| 风险 | 主要测试位置 |
|---|---|
| 信源格式、全文与 SSRF | `test_rss_adapter.py`、`test_new_adapters.py`、`test_fulltext_gate.py`、`test_ssrf.py` |
| 幂等、版本和加工 | `test_processing.py`、`test_worker.py`、`test_rechunk_invariant.py` |
| Story、精选、报告 | `test_story.py`、`test_selection_topics.py`、`test_report.py` |
| RAG 检索/生成/引用 | `test_rag_*.py`、`test_chunk_quality.py`、`data/golden/` |
| Java 权限、发布、订阅 | `apps/core-api/src/test/` |
| Web 代理、组件与导航 | `*.test.ts`、`e2e/*.spec.ts` |
| 部署和端口隔离 | `test_prod_compose.py`、`test_production_delivery.py` |

## 8. 读完后的自检

你应能解释：PostgreSQL 为什么是唯一事实源；文章、修订、分块与 Story 为什么分表；
RSS 摘要为什么不能做最终证据；Dense/Sparse/Temporal/RRF/Reranker 分别解决什么；
引用为何由服务端反查；报告失败为何不阻塞资讯；Redis 丢失会发生什么；以及一次 PR 如何成为
生产不可变镜像。回答不清楚时回到对应链路，而不是继续背更多文件名。

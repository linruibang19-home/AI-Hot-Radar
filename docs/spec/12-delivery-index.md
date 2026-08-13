# 12｜完整交付索引

文档 ID：`AHR-INDEX-1200`

版本：`v1.4.0`
更新时间：2026-08-12

## 1. 当前交付状态

本仓库已经不是“等待 TASK-M0 创建源码”的规格包，而是可由 Docker Compose 启动的完整
实现。M0–M5 首次生产闭环已经完成；香港目标机、系统加固、Docker、DNS、Caddy HTTPS、
生产 SMTP、真实告警与异机备份均已投入运行。当前生产运行基线为
`v0.1.7@c1c6918`；服务器 checkout、`IMAGE_TAG` 与运行镜像对齐该提交。GitHub `main`
允许包含尚未发布的运维与文档提交，因此不能用 `main` 代替运行镜像 revision 判断线上版本。
权威入口按用途分为：

| 需要了解什么 | 首选文档 |
|---|---|
| 五分钟了解项目、运行与核心指标 | `README.md` |
| 从业务到代码系统学习 | `docs/handbook/README.md` |
| 面试复习、题库、简历与演示 | `docs/interview/README.md` |
| 腾讯云 Ubuntu 24.04 迁移与购买基线 | `docs/status/operations/tencent-cloud-migration-readiness-20260812.md` |
| 作品集页面语义、截图与验证 | `docs/status/delivery/portfolio-closeout-20260812.md` |
| 当前提交、容器、数据快照和下一步 | `docs/status/current/handoff-20260812.md` |
| 导航性能根因与回归 | `docs/status/operations/navigation-performance-20260812.md` |
| 完整历史、根因和逐轮实验 | `docs/status/current/project-status.md` |
| 全部代码的业务链路与学习顺序 | `docs/code-map.md` |
| 状态、历史快照与实验证据分类 | `docs/status/README.md` |
| 仓库清理和可恢复归档证据 | `docs/status/operations/repository-hygiene-20260812.md` |
| RAG 当前发布门禁 | `docs/status/product/rag-specialist-audit-20260811.md` |
| RAG 安全、超时和 SLO | `docs/status/product/rag-security-performance-20260811.md` |
| RAG 问答 UI 精修 | `docs/status/product/rag-ui-polish-20260811.md` |
| 邮箱订阅与定时投递 | `docs/status/product/report-subscriptions-20260811.md` |
| v0.1.6 精选与订阅生产验收 | `docs/status/product/v016-selection-email-20260812.md` |
| DeepSeek 生成模型配置 | `docs/status/product/generation-model-selection-20260811.md` |
| RAG 质量/运行页面 | `docs/status/product/rag-operations-ui-20260811.md` |
| 上线前最终本地门禁 | `docs/status/delivery/prelaunch-release-gate-20260811.md` |
| 生产预检与恢复演练 | `docs/status/delivery/production-preflight-20260811.md` |
| 首次生产部署与外部闸门 | `docs/status/delivery/production-deployment-20260811.md` |
| 锁定产品与技术决策 | `docs/spec/00-master-spec.md` + `docs/adr/` |
| 下一张任务卡 | `docs/spec/08-roadmap-ai-ide.md` |

`docs/status/history/handoff-20260810.md` 是历史交接快照，已由 08-11 版本取代，不应再用其中的
分支、提交、测试数和待办判断当前状态。

## 2. 可执行产品

| 路径 | 内容 | 当前状态 |
|---|---|---|
| `apps/web/` | Next.js 15 App Router 网站、RAG UI、评测与运维页 | 已实现；当前镜像健康 |
| `apps/core-api/` | Spring Boot 3 内容、报告与管理 API | 已实现；当前镜像健康 |
| `apps/ai-service/` | FastAPI 采集、加工、聚类、报告与 RAG | 已实现；当前镜像健康 |
| `database/migrations/` | Flyway V001–V025（含 V017.1） | 当前库与空库升级通过；V023 订阅、V024 模型配置、V025 可审计主题关系已执行 |
| `infra/compose/docker-compose.yml` | 本地唯一启动入口 | 已验证 |
| `infra/compose/docker-compose.prod.yml` | 生产 Compose | 目标机运行；真实配置缺危险值时仍 fail-closed |
| `infra/caddy/Caddyfile` | HTTPS 反向代理 | `aihotradar.online` 证书已签发并自动续期 |
| `.github/workflows/release.yml` | GHCR 构建发布 | `v0.1.7` 完整 CI 与三镜像发布成功 |
| `infra/scripts/backup.sh` | PostgreSQL 定时备份 | 已实现目录校验与 SHA-256；本地真实恢复通过 |
| `infra/scripts/preflight.sh` / `deploy-production.sh` | 生产配置与不可变提交部署门禁 | 目标机 preflight 与 `v0.1.7` 不可变 SHA 部署均已验证 |
| `infra/scripts/monitor.py` / `smoke-production.sh` | 健康、备份年龄告警与公网验收 | Gmail SMTP 故障/恢复实收与公网 smoke 通过 |
| `infra/scripts/restore-verify.sh` | 受保护隔离恢复核验 | 本地真实 100 MB dump 恢复通过 |
| `api/openapi.yaml` / `schemas/` | 服务契约与生成类型来源 | 生成无 diff |
| `config/` | 140 信源、9 类 Profile、taxonomy 与受限 watchlist | 已加载；社交监控保持关闭 |

当前公开页面：`/`、`/items`、`/hot`、`/stories`、`/topics`、`/reports`、`/ask`、
`/eval`、`/ops`、`/admin/models`、`/admin/sources`。日报、周报、月报均可生成并经确定性
门禁自动发布；当前数据库 15 份报告均为 PUBLISHED。邮箱双重确认订阅、定时投递、退订和
DeepSeek 生成模型白名单切换已完成；生产 SMTP 已实投。ChromeCodex 插件仍有本机内核
路径故障，真实浏览器验收改由本机 Chrome + Playwright 与官方 Playwright 容器完成。

## 3. 规格与设计

| 路径 | 作用 | 状态 |
|---|---|---|
| `README.md` | 产品与工程总入口 | 当前 |
| `AGENTS.md` / `CLAUDE.md` / `.cursor/rules/*` | AI IDE 执行约束 | 当前 |
| `docs/spec/00-master-spec.md` | 唯一总规格与锁定决策 | 锁定 |
| `docs/spec/01-product-requirements.md` | 产品、页面与发布门槛 | 锁定 |
| `docs/spec/02-system-architecture.md` | 服务、数据与部署边界 | 锁定 |
| `docs/spec/03-data-ingestion.md` | 数据模型、采集、去重、Story | 锁定 |
| `docs/spec/04-rag-agent-design.md` | 时间/事件感知混合 RAG | 锁定 |
| `docs/spec/05-api-contract.md` | API 语义 | 锁定 |
| `docs/spec/06-frontend-spec.md` | 路由、组件、状态与可访问性 | 锁定 |
| `docs/spec/07-quality-security-ops.md` | 测试、安全、版权与运维 | 锁定 |
| `docs/spec/08-roadmap-ai-ide.md` | 里程碑与可验收任务卡 | 持续更新 |
| `docs/spec/09-source-registry-fulltext.md` | 信源与全文门禁 | 锁定 |
| `docs/spec/10-source-adapter-implementation.md` | Adapter 实现边界 | 锁定 |
| `docs/spec/11-end-to-end-runbook.md` | 全链路运行与恢复 | 当前 |
| `docs/design/` | RAG 评测、实现和部署设计 | 当前 |
| `docs/code-map.md` | 全部源码、迁移、配置、基础设施与测试的学习地图 | 当前 |
| `docs/adr/` | 已锁定架构决策与回滚条件 | 当前至 ADR-0029 |
| `docs/handbook/` | 业务、数据、三端、RAG、部署与测试的 15 章工程教材 | 当前 |
| `docs/interview/` | 00–12 面试表达、120 题、10 个 STAR、代码走读和学习计划 | 当前 |
| `docs/assets/screenshots/` | README 使用的脱敏本地页面截图 | 2026-08-12 封版 |

## 4. 当前交付证据

- Python：Ruff、mypy 86 个源码文件、pytest 884 passed / 2 skipped；
- Java：Maven verify 74/74；
- Web：npm audit 0、typecheck、lint、Vitest 73/73、Next.js 15.5.23 production build；
- 数据库：140 个信源、2040 条内容、8089 个分块且 100% 向量化、1622 个 Story；
- RAG：主集 Recall@20 0.8994、专项集 0.9333、引用完整性 0.9881、段落支持度
  0.9344、拒答准确率 1.0000、关键问题 P0 为 0；
- 运行态：PostgreSQL、Redis、Core API、AI Service、Web 健康，`/ask` 返回 200；
- 报告：日报 11、周报 3、月报 1，均为 PUBLISHED；邮箱订阅闭环已用 Mailpit 验收。
- 数据恢复：102 MiB V024 dump 目录/SHA 校验与隔离恢复通过。
- 部署：Ubuntu 22.04 目标机已加固并运行 `v0.1.7@c1c6918`；10 个容器运行，HTTPS、
  真实模型/SMTP/告警、异机备份与隔离恢复通过。

证据与限制分别见本页 §1 指向的四份 08-11 状态文档；不要脱离 run、样本量和口径引用
单个指标。

## 5. 后续交付顺序

1. 迁移 P0：新广州机平行部署、备份恢复、临时地址 smoke、备案完成后 DNS 切换与回切演练；
2. 运维 P1：迁移自有域名发件服务，配置 SPF/DKIM/DMARC、退信/投诉处理；每月恢复演练；
3. 产品 P1：补管理写操作 UI、加工任务重跑入口和用户反馈闭环；
4. RAG P1：扩大实体/时间人工标注与噪声集，解决 SLA 类目标原文稳定排第 27 的缺口；
5. 产品化 P2：版本化知识快照、账号/租户/ACL（只在私有语料进入范围后）。

执行时仍必须一次只领取 `08-roadmap-ai-ide.md` 中的一张任务卡；不得因为本索引列出后续
事项而并行扩大里程碑范围。

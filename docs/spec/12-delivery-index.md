# 12｜完整交付索引

文档 ID：`AHR-INDEX-1200`

版本：`v1.3.1`
更新时间：2026-08-11

## 1. 当前交付状态

本仓库已经不是“等待 TASK-M0 创建源码”的规格包，而是可由 Docker Compose 启动的完整
实现。M0–M4 的功能与本地发布门禁已经完成；M5 部署产物已存在，但服务器、新密钥、
目标服务器上的 DNS/TLS、真实告警投递和异机备份尚未执行；本地真实备份恢复演练已通过。

当前工作分支为 `codex/rag-quality-gates`。权威入口按用途分为：

| 需要了解什么 | 首选文档 |
|---|---|
| 五分钟了解项目、运行与核心指标 | `README.md` |
| 当前提交、容器、数据快照和下一步 | `docs/status/handoff-20260811.md` |
| 完整历史、根因和逐轮实验 | `docs/status/project-status.md` |
| RAG 当前发布门禁 | `docs/status/rag-specialist-audit-20260811.md` |
| RAG 安全、超时和 SLO | `docs/status/rag-security-performance-20260811.md` |
| RAG 问答 UI 精修 | `docs/status/rag-ui-polish-20260811.md` |
| 生产预检与恢复演练 | `docs/status/production-preflight-20260811.md` |
| 锁定产品与技术决策 | `docs/spec/00-master-spec.md` + `docs/adr/` |
| 下一张任务卡 | `docs/spec/08-roadmap-ai-ide.md` |

`docs/status/handoff-20260810.md` 是历史交接快照，已由 08-11 版本取代，不应再用其中的
分支、提交、测试数和待办判断当前状态。

## 2. 可执行产品

| 路径 | 内容 | 当前状态 |
|---|---|---|
| `apps/web/` | Next.js 15 App Router 网站、RAG UI、评测与运维页 | 已实现；当前镜像健康 |
| `apps/core-api/` | Spring Boot 3 内容、报告与管理 API | 已实现；当前镜像健康 |
| `apps/ai-service/` | FastAPI 采集、加工、聚类、报告与 RAG | 已实现；当前镜像健康 |
| `database/migrations/` | Flyway V001–V022（含 V017.1） | 当前库升级通过；V022 报告发布迁移已执行 |
| `infra/compose/docker-compose.yml` | 本地唯一启动入口 | 已验证 |
| `infra/compose/docker-compose.prod.yml` | 生产 Compose | 产物就绪，未在目标服务器执行 |
| `infra/caddy/Caddyfile` | HTTPS 反向代理 | 产物就绪，待域名与证书 |
| `.github/workflows/release.yml` | GHCR 构建发布 | 已实现，未替代人工首次上线验收 |
| `infra/scripts/backup.sh` | PostgreSQL 定时备份 | 已实现目录校验与 SHA-256；本地真实恢复通过 |
| `infra/scripts/preflight.sh` / `deploy-production.sh` | 生产配置与不可变提交部署门禁 | 本地验证通过，待目标机执行 |
| `infra/scripts/monitor.py` / `smoke-production.sh` | 健康、备份年龄告警与公网验收 | 逻辑验证通过，待接真实 HTTPS webhook |
| `infra/scripts/restore-verify.sh` | 受保护隔离恢复核验 | 本地真实 100 MB dump 恢复通过 |
| `api/openapi.yaml` / `schemas/` | 服务契约与生成类型来源 | 生成无 diff |
| `config/` | 140 信源、9 类 Profile、taxonomy 与受限 watchlist | 已加载；社交监控保持关闭 |

当前公开页面：`/`、`/items`、`/hot`、`/stories`、`/topics`、`/reports`、`/ask`、
`/eval`、`/ops`、`/admin/sources`。日报、周报、月报均可生成并经确定性门禁自动发布；
当前数据库 14 份报告均为 PUBLISHED。受保护的发布/撤回 API 已完成，浏览器管理写 UI、
订阅与定时邮件仍是待办。

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
| `docs/adr/` | 已锁定架构决策与回滚条件 | 当前至 ADR-0025 |

## 4. 当前交付证据

- Python：Ruff、mypy 86 个源码文件、pytest 878/878；
- Java：Maven test 62/62；
- Web：typecheck、lint、Vitest 55/55、Next.js 15.5.23 production build；
- 数据库：140 个信源、1855 条内容、7057 个分块且 100% 向量化、1448 个 Story；
- RAG：主集 Recall@20 0.8994、专项集 0.9333、引用完整性 0.9881、段落支持度
  0.9344、拒答准确率 1.0000、关键问题 P0 为 0；
- 运行态：PostgreSQL、Redis、Core API、AI Service、Web 健康，`/ask` 返回 200；
- 报告：日报 10、周报 3、月报 1，均为 PUBLISHED；公开 API 只读取 PUBLISHED。

证据与限制分别见本页 §1 指向的四份 08-11 状态文档；不要脱离 run、样本量和口径引用
单个指标。

## 5. 后续交付顺序

1. 上线 P0（需主人/服务器权限）：轮换全部密钥、设置供应商消费上限、配置服务器、
   DNS/TLS、HTTPS 告警 webhook 与异机备份；
2. 上线 P0（需主人/服务器权限）：用 `deploy-production.sh` 按提交 SHA 首次部署，执行公网
   smoke、目标机隔离恢复和告警/恢复通知演练；
3. 产品 P1：在明确订阅者、退订和时区策略后补报告定时投递；补管理写操作 UI 与加工任务重跑入口；
4. RAG P1：扩大实体/时间人工标注与噪声集，解决 SLA 类目标原文稳定排第 27 的缺口；
5. 产品化 P2：反馈闭环、版本化知识快照、账号/租户/ACL（只在私有语料进入范围后）。

执行时仍必须一次只领取 `08-roadmap-ai-ide.md` 中的一张任务卡；不得因为本索引列出后续
事项而并行扩大里程碑范围。

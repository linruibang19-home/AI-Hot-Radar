# 08｜开发路线与 AI IDE 执行规范

文档 ID：`AHR-ROADMAP-800`

## 1. 执行原则

Codex、Claude Code、Cursor 使用同一套规格，不为不同工具维护互相冲突的需求。根目录 `AGENTS.md`、`CLAUDE.md` 和 Cursor rule 只负责告诉执行器如何读取本规格，不复制业务真相。

每次开发只领取一个可验收任务卡，步骤为：

```text
读取总规格与专项文档
→ 检查现有代码/测试/迁移
→ 写最小实施计划
→ 实现与测试
→ 运行该任务验收命令
→ 更新文档/ADR
→ 汇报变更、证据、风险与下一步
```

## 2. 里程碑

### M0｜工程骨架（3–5 天）

- monorepo 目录；
- Next.js、Spring Boot、FastAPI 健康检查；
- PostgreSQL + pgvector、Redis、Docker Compose；
- Flyway、统一 request ID、基础 OTel；
- OpenAPI/JSON Schema 生成链路；
- CI lint/test/build。

验收：一条命令启动；三服务 health 通过；空库迁移成功；契约生成无 diff。

### M1｜真实信源与原始入库（5–8 天）

- 导入 `sources.yaml` 与 `social-watchlist.yaml`，但社交目标默认关闭；
- 实现 RSS/Atom、Docs Changelog、GitHub Release API、arXiv 与 Article Fulltext adapter；
- source cursor、ETag/Last-Modified、crawl run；
- URL 规范化、raw_document、outbox；
- 重试、限流、SSRF 防护和 fixture 测试；
- 后台信源/任务只读页。

验收：Wave A 至少 50 个一手源通过探测，至少 30 个真实源连续运行 24h；其中 20 个完成文章全文或完整 Release 解析；重复执行不重复入库；304 正常；可定位失败。

### M2｜内容加工与网站（8–12 天）

- 正文抽取和结构切块；
- 完全/近似重复；
- LLM JSON 结构化、实体/主题归一；
- 质量评分和精选；
- 首页、全部动态、详情、搜索、主题、后台重跑；
- 日报生成与测试邮件。

验收：500 条真实内容；页面端到端；模型不可用时已有内容仍可浏览。

### M3｜Story 与热点（5–8 天）

- 候选生成、聚类、主来源、独立信源；
- Story 详情和时间线；
- 合并/拆分/锁定；
- 热度算法；
- report 从 Story 生成；
- 根据压测决定是否引入 RabbitMQ。

验收：100 个 Story 人工抽检达到 `AHR-KPI-003`；人工锁定不被自动覆盖。

### M4｜RAG MVP（8–12 天）

- story/item/passage Embedding；
- Planner 与 RetrievalPlan；
- SQL/FTS/Vector 召回、RRF、Rerank；
- Story 折叠、上下文扩展、证据选择；
- SSE、引用绑定、拒答；
- 80+ 题黄金集和回归报告。

验收：达到 RAG 发布门禁；所有事实引用可跳回 passage 和原文。

### M5｜上线与增强（5–8 天）

- 域名、HTTPS、备份、监控和告警；
- 邮件订阅、退订、投递记录；
- 周报/月报；
- 增量 API、RSS 输出；
- 性能、故障和恢复演练；
- 版权/隐私/关于/下架页面。

## 3. 第一批任务卡

### TASK-M0-001｜初始化仓库

**输入**：本规格书。  
**允许修改**：根目录、`apps/**`、`infra/**`、CI。  
**禁止**：开始写业务页面、引入 Kafka/Kubernetes。  
**完成标准**：三个服务、Compose、health、README 启动说明和 CI。

### TASK-M1-001｜信源模型与 RSS Adapter

**读取**：`03-data-ingestion.md`、`09-source-registry-fulltext.md`、`config/sources.yaml`、`config/social-watchlist.yaml`。  
**产出**：Flyway 表、source loader、adapter、cursor、fixture、集成测试。  
**关键测试**：同 feed 重放、更新条目、缺失 guid、文章回源、正文质量门禁、304、429、超时、非法 URL。

### TASK-M1-002｜全文回源与信源健康门禁

**读取**：`09-source-registry-fulltext.md`、`07-quality-security-ops.md`。  
**产出**：profile adapter、站点 fixture、正文质量评分、CONFIGURED/PROBING/ACTIVE/DEGRADED/QUARANTINED 状态机、`source-health.json`。  
**完成标准**：不得把 RSS/搜索摘要计入全文；Wave A 20 个来源最新 3 篇中至少 2 篇正文合格；失败来源自动降级且保留原因。

### TASK-M1-003｜GitHub、Changelog、arXiv 与公开 API

**读取**：`10-source-adapter-implementation.md`、`config/ingestion-profiles.yaml`、`config/site-overrides.yaml`。  
**产出**：GitHub Releases 分页/限额 Adapter、Changelog revision diff、arXiv HTML/PDF、Hugging Face model card、OpenAlex 元数据 Adapter。  
**关键测试**：GitHub Link 分页/ETag/空 body，Changelog heading 更新，arXiv HTML 缺失转 PDF，模型卡 404，OpenAlex cursor；所有 fixture 均可离线重放。  
**完成标准**：每类至少 2 个真实 canary（OpenAlex 1 个即可），原始响应、字段映射、游标与错误分类可追溯。

### TASK-M2-001｜内容加工契约

**产出**：Pydantic schema、JSON Schema、Java generated DTO、Prompt v1、失败修复一次、dead-letter。  
**禁止**：解析失败时把自由文本直接写进结构化列。

### TASK-M4-001｜RAG 检索基线

**产出**：黄金集、SQL/FTS baseline、Vector baseline、RRF、离线报告。  
**顺序**：先测 baseline，再加 reranker；不得只展示几个主观示例宣布有效。

### TASK-M5-001｜发布基线整合与全量门禁

**状态**：✅ 2026-08-11 完成；验收记录见 `docs/status/project-status.md` §0。
**读取**：`07-quality-security-ops.md`、`11-end-to-end-runbook.md`、
`12-delivery-index.md`、`docs/status/project-status.md`。
**输入**：当前已由 Docker Compose 实测运行的最新开发分支。
**产出**：以最新开发提交为起点的正式发布候选基线、可重复的全量验收记录，
以及与实测结果一致的状态文档。
**关键测试**：Python pytest/mypy、Java Maven test、Web typecheck/lint/unit、
契约生成无 diff、Compose 服务健康、数据库迁移与核心页面/API smoke。
**完成标准**：所有门禁通过；失败项有根因和修复证据；发布候选可 fast-forward
纳入 `main`；不打印或提交 `.env`，不推送远端，不执行生产部署。

### TASK-M4-002｜RAG 专项黄金集与引用发布门禁

**状态**：✅ 2026-08-11 完成。15 题专项集、8 个真实近邻噪声、同候选快照 A/B、
90 题检索/生成回归、数值关系审计与逐题人工 P0 核验均已落地；证据见
`docs/status/rag-specialist-audit-20260811.md`。Planner 的 query-type 代理经扫描确认
在当前语料上不可操作，未用默认关闭的 LLM 结果冒充线上门禁通过。
**读取**：`04-rag-agent-design.md`、`07-quality-security-ops.md`、
`docs/design/m4-rag-evaluation.md`、`data/golden/README.md`、
`docs/status/rag-product-readiness-20260810.md`。
**输入**：现有 90 题黄金集、ENTITY/B15/GEN 基线和线上 `rag_query` 证据链。
**产出**：中文厂商名到英文产品/模型的专项黄金集、噪声敏感性样本、同候选快照
的重排 A/B、关键问题逐条人工引用核验，以及可阻断发布的回归结果。
**边界**：先用专项集证明召回缺口；只有缺口成立才试验查询改写。改写只能新增
候选，不得改变冻结的原始问题、实体、时间窗或覆盖原始查询结果。
**完成标准**：每个样本均由原始 passage 人工核验；关键问题不存在“引用存在但
不支持结论”的 P0；回归绑定 `eval_run_id`、候选快照、模型/配置版本，结果可复现。

### TASK-M4-003｜RAG 上线前安全与性能稳定性

**状态**：✅ 2026-08-11 完成。安全边界、凭据 fail-closed、供应商快速失败、分阶段
p95/p99 SLO、全库门禁与当前镜像 smoke 均已验证；服务器依赖项按边界保留。证据见
`docs/status/rag-security-performance-20260811.md`。
**读取**：`04-rag-agent-design.md`、`07-quality-security-ops.md`、
`docs/status/rag-product-readiness-20260810.md`、ADR-0017、ADR-0023、ADR-0024。
**输入**：当前公开问答入口、原始网页证据、三类供应商调用、`rag_query.metrics` 与
08-11 全量延迟证据。
**产出**：不可信证据提示边界、最终答案凭据泄漏 fail-closed、可配置且有界的供应商
超时/尝试次数、分阶段 p95/p99 SLO 判定、Compose 当前源码全量门禁。
**边界**：不按关键词删除安全类文章；不引入新中间件；没有第二供应商真实配置与回归时
不宣称备用模型已完成；密钥轮换、DNS/TLS、真实告警和恢复演练留到服务器就绪后执行。
**完成标准**：安全 canary、超时/重试和 SLO 单测通过；Ruff、全库 mypy、全量 pytest
通过；Compose 服务健康，公开 API smoke 无回归。

### TASK-M4-004｜RAG 问答界面精修与可信引导

**状态**：✅ 2026-08-11 完成；验收记录见
`docs/status/rag-ui-polish-20260811.md`。
**读取**：`06-frontend-spec.md`、`04-rag-agent-design.md`。
**输入**：现有 `/ask` 多轮对话、示例问题、证据质量与引用交互。
**产出**：不改变页面骨架的空状态层级、能力边界提示、示例问题布局、输入区视觉与
键盘焦点精修，以及对应的前端回归测试。
**边界**：保留侧栏、标题、对话头、答案卡片和引用结构；不引入新组件库或整页重做；
不得用“智能”“准确”等无法验证的宣传词替代具体产品能力。
**完成标准**：空状态在桌面与移动端均无大面积无意义留白；一眼可见原文引用、时间范围
和证据不足拒答三项边界；typecheck、lint、unit 与 production build 通过；Docker 当前
镜像 `/ask` 可访问且包含新版可信提示。

### TASK-DOC-001｜发布候选文档与交接收口

**状态**：✅ 2026-08-11 完成；当前交接见
`docs/status/handoff-20260811.md`。
**读取**：`README.md`、`12-delivery-index.md`、`docs/status/project-status.md`、
`docs/status/handoff-20260810.md` 以及 08-11 三份 RAG 验收记录。
**输入**：当前 Git 分支/提交、Docker Compose 运行态、数据库实测快照与本轮门禁结果。
**产出**：更新总入口、交付索引、累计项目状态和新的当前交接文档；旧交接保留为历史记录。
**完成标准**：当前分支、数据量、测试数、RAG 门禁、报告状态和剩余任务在各入口口径一致；
不把服务器权限事项、人工视觉验收或未来产品化能力写成已完成。

### TASK-M5-002｜报告阅读体验与结构化只读模型

**状态**：🟡 2026-08-11 实现与自动化验收完成，Chrome 视觉门禁待补；证据见
`docs/status/report-reader-20260811.md`。
**读取**：`01-product-requirements.md`、`06-frontend-spec.md`、
`docs/status/handoff-20260811.md`。
**输入**：现有 daily/weekly/monthly DRAFT 报告、`report_item` 证据关系和当前报告路由。
**产出**：向后兼容的结构化报告只读 API；保留全站侧栏的“档案栏 + 刊物正文”报告界面；
日报、周报、月报使用同一组件但呈现不同周期语义；桌面与移动端可用。
**边界**：不得复制 AIHOT 品牌、Logo、完整文案或像素布局；不得新增浏览器写凭据；
本卡不实现人工发布、下架或编辑，DRAFT 必须明确显示；不新增数据库表或迁移。
**完成标准**：详情返回真实 `report_item`、来源、Story、章节、统计与前后期导航；三周期
页面可访问；Python 报告测试、Java 测试、Web typecheck/lint/unit/build、Docker smoke 和
Chrome 桌面/窄屏验收通过。

### TASK-M5-003｜非阻塞报告发布状态机与审核 API

**状态**：✅ 2026-08-11 完成；决策见 ADR-0025，验收见
`docs/status/report-publication-20260811.md`。
**读取**：`01-product-requirements.md`、`05-api-contract.md`、
`07-quality-security-ops.md`、`11-end-to-end-runbook.md`、ADR-0019、ADR-0025。
**输入**：持续生成的 daily/weekly/monthly DRAFT、现有 OPERATOR Bearer 鉴权与
`admin_audit`、手工 `send-report`。
**产出**：确定性自动发布门禁、PUBLISHED 公共读取、受保护的报告发布/下架与预览 API、
持久化幂等键、正式邮件状态保护及历史 DRAFT 安全回填。
**边界**：报告状态不得参与内容入库、精选、Story 或 RAG；不得在浏览器或 Web 容器加入
OPERATOR 凭据；本卡不实现订阅、自动邮件调度或管理写 UI。
**完成标准**：合格报告可自动发布，不合格报告进入 REVIEW_REQUIRED，WITHDRAWN 不被
pipeline 自动解除；正式邮件拒绝非 PUBLISHED、dry-run 可预览；管理变更满足 RBAC、
二次确认、幂等和审计；历史报告不丢失；Python/Java/Flyway/Compose smoke 通过。

### TASK-M5-004｜报告订阅与定时投递闭环

**状态**：✅ 2026-08-11 完成；与 TASK-M5-003 分卡实现并独立提交验收。
**读取**：`01-product-requirements.md`、`05-api-contract.md`、
`07-quality-security-ops.md`、`11-end-to-end-runbook.md`、ADR-0025。
**输入**：只允许投递 PUBLISHED 的 `send-report`、现有 `delivery_log` 与报告周期状态。
**产出**：明确收件人/订阅事实模型、daily/weekly/monthly 定时投递、失败重试与可观测状态。
**边界**：在收件人来源、退订语义和时区策略得到确认前不得默认群发；不得把
`outbox_event` 描述成已有消费者；投递失败不得反向阻塞采集、精选或站内报告发布。
**完成标准**：同一期同一收件人至多一次正式投递；只发送 PUBLISHED；失败可重试、可审计、
可人工 dry-run；无订阅者时安全空跑；Compose 运行态与邮件沙箱验收通过。
**当前证据**：ADR-0026、Flyway V023、`docs/status/report-subscriptions-20260811.md`。
Core API 持有双重确认、订阅与投递事实，Web 只做代理和交互；本地 Mailpit 已实测申请、确认、
PUBLISHED 投递、在线阅读链接与退订，验收数据随后清理。

### TASK-M5-005｜生产部署预检与恢复门禁

**状态**：✅ 2026-08-11 完成；所有不依赖目标服务器的上线准备与本地真实恢复演练通过。
**读取**：`02-system-architecture.md`、`07-quality-security-ops.md`、
`11-end-to-end-runbook.md`、`docs/design/m5-deployment.md`、
`docs/design/m5-first-deploy-checklist.md`。
**输入**：现有 production Compose、Caddy、GHCR release workflow、备份 worker、当前本地
Compose 与已通过的 M4/M5 质量门禁。
**产出**：可执行的生产环境预检、不可变镜像与密钥占位检查、正确的 Cloudflare 客户端 IP
信任链、同提交发布测试门、内部端口不暴露、备份完整性检查、隔离恢复演练和公网 smoke。
**边界**：不创建或轮换真实供应商密钥，不修改 DNS/Cloudflare/服务器防火墙，不 push、
打 tag 或部署；这些动作必须在主人提供目标机与相应权限后执行。TASK-M5-004 作为独立 P1
后来已由 Core API 完成，没有把订阅功能塞进 ai-service 违反服务边界。
**完成标准**：生产 Compose 使用脱敏 fixture 可完整解析；危险默认值会被预检拒绝；release
只有同提交全量门禁通过后才构建推送；本地真实数据库完成 dump/restore 数据核对；本地核心
服务与关键页面保持健康；文档明确目标服务器到位后仅剩的外部执行步骤。

### TASK-M5-006｜首次生产部署与外部闭环

**状态**：✅ 2026-08-12 完成；首次生产闭环见
`docs/status/production-deployment-20260811.md`，当前交接见
`docs/status/handoff-20260812.md`。
**读取**：`02-system-architecture.md`、`07-quality-security-ops.md`、
`11-end-to-end-runbook.md`、`docs/design/m5-deployment.md`、
`docs/design/m5-first-deploy-checklist.md`、TASK-M5-005 验收记录。
**输入**：主人待提供的新域名、香港 2C4G 目标服务器、公网部署脚本、不可变镜像发布门和
本地恢复证据。旧 `kuritian.online` 不续费，不再作为本卡上线域名。
**产出**：专用 SSH 密钥与非 root 运维边界、目标机系统审计、Docker/防火墙、生产配置、
DNS/Caddy TLS、按提交 SHA 的首次部署、公网 smoke、真实告警、异机备份和恢复复演。
**边界**：聊天中出现的口令视为泄露，不在命令、文件或日志中复述/使用；真实密钥不得进入
Git；出租方账号下的服务器按半可信主机处理，模型密钥必须专用且低额度；删除、覆盖数据库、
关闭 SSH 或变更域名所有权前必须有明确且可恢复的目标；已完成的 TASK-M5-004 不改变这些
生产安全边界。
**完成标准**：域名续费与 A 记录生效；80/443 只到 Caddy，内部端口公网不可达；HTTPS
证书与安全头通过；核心服务健康；AI 动态、精选、三周期报告与 RAG 公网可用；
告警失败/恢复均实收；异机备份存在且隔离恢复成功；部署提交、RPO/RTO 和回滚命令有记录。
**当前证据**：首次上线由 `v0.1.4@6e192a7` 关闭；导航维护版本 `v0.1.5@d58e639` 的
GitHub Release、服务器 checkout、`IMAGE_TAG` 与三张业务
镜像一致；10 个生产容器运行，核心健康检查通过。`aihotradar.online` 的 Caddy HTTPS、
公网 smoke、真实 RAG 引用、Gmail SMTP 实投、故障/恢复告警、校验和异机备份与 V024
隔离恢复均通过。首次生产目标已经关闭，后续升级按独立维护任务走 PR/Release/SHA 部署。

### TASK-M5-007｜DeepSeek 生成模型可见、可切换、可审计

**状态**：✅ 2026-08-11 完成；验收见
`docs/status/generation-model-selection-20260811.md`。
**读取**：`01-product-requirements.md`、`05-api-contract.md`、
`06-frontend-spec.md`、`07-quality-security-ops.md`、ADR-0027。
**输入**：现有 DeepSeek OpenAI-compatible 客户端、`llm_usage`、Core Admin RBAC/审计与
工程页面；硅基流动 embedding/reranker 保持现状。
**产出**：受控模型目录、PostgreSQL 当前配置与版本、受保护的读取/切换 API、模型配置页，
以及按实际模型配置快照记录的生成用量。
**边界**：只开放 `deepseek-v4-flash` / `deepseek-v4-pro`；不保存或显示 API key；不开放
任意模型字符串；不切换 embedding/reranker；不自动重算历史内容或历史向量；thinking 默认
显式关闭，未经专项回归不开放。
**完成标准**：OPERATOR 切换满足二次确认、幂等和审计；新生成调用采用新配置版本，历史
调用保留原模型与价目快照；VIEWER 只能读取；Java/Python/Web/Flyway/Compose 回归通过。

### TASK-M5-008｜RAG 质量与运行页面产品化收口

**状态**：✅ 2026-08-11 完成；验收见
`docs/status/rag-operations-ui-20260811.md`。
**读取**：`04-rag-agent-design.md`、`06-frontend-spec.md`、
`07-quality-security-ops.md`、TASK-M4-002、ADR-0021、ADR-0027。
**输入**：既有 90 题检索/生成评测快照、线上 `rag_query` / `llm_usage` 聚合、
模型配置与不可变价目快照。
**产出**：在不删除原始实验记录、不改变原页面视觉语言的前提下，把 `/eval` 改为先给出
发布门禁与剩余风险的 RAG 质量页，把 `/ops` 改为先给出 SLO、成本口径、瓶颈和建议动作的
运行页；历史价目缺失必须明确标为 legacy fallback，不能冒充实际账单。
**边界**：不修改检索策略、黄金集或评测结果；不新增基础设施；不把自动引用精度当作人工
正确性；不把供应商价目估算写成真实扣费；底层逐轮记录与阶段明细必须仍可查看。
**完成标准**：页面首屏能回答“是否达标、哪里有风险、下一步做什么”；价目来源可逐行追溯；
Web 类型、Lint、测试、构建与 Docker 运行态通过，Chrome 视觉验收若受工具故障阻塞必须如实记录。

### TASK-M5-009｜生产精选时间语义与邮件订阅体验收口

**状态**：✅ 2026-08-12 完成并随 `v0.1.6@6f03e75` 上线。
**读取**：`03-data-ingestion.md`、`06-frontend-spec.md`、`09-source-registry-fulltext.md`、
`10-source-adapter-implementation.md`、TASK-M5-004。
**输入**：生产首页当天 12 条精选均来自 arXiv 且显示 12:00 的实测、现有双重确认邮件订阅、
生产 SMTP 与定时投递服务。
**产出**：按 `Asia/Shanghai` 计算精选日；为同一来源族和研究内容设置可解释的日配额；
日期/批次精度来源不伪装成精确分钟；订阅弹窗明确确认、发送内容、发送时机和退订语义，
并完成受控邮箱的生产确认与一期报告投递验收。
**边界**：不修改信源原始 `published_at`，不凭抓取时间伪造论文发布时间；不发送逐条动态；
不绕过 PUBLISHED 门禁；不新增邮件旁路、消息队列或用户账号体系。
**完成标准**：当天非 arXiv 候选可进入当天精选，arXiv 不再占满整日；精确时间来源仍显示
时分、arXiv 显示批次语义；邮件 UI 在提交前后均能回答“会收到什么/何时收到”；Python、
Java、Web、Compose 与公网桌面/移动端验收通过，发布后数据库和页面证据写入状态文档。
**当前证据**：`docs/status/v016-selection-email-20260812.md`；生产当天 12 条精选已分布到
8 个来源族，arXiv 仅 2 条；1 个日报订阅已显式确认，下一期开始投递。

### TASK-M5-010｜工程数据时效语义与作品集封版

**状态**：✅ 2026-08-12 完成；代码、脱敏截图与面试材料已通过本地门禁，等待发布验收。
**读取**：`06-frontend-spec.md`、`07-quality-security-ops.md`、TASK-M5-008、
TASK-M5-009、`docs/status/handoff-20260812.md`。
**输入**：现有 `/eval` 版本化评测摘要、动态信源健康数据、生产页面与发布证据。
**产出**：明确区分静态发布评测与动态运行状态；为信源后台提供可理解的刷新时间语义；
用脱敏生产截图、分层 README 与面试学习材料完成公开作品集封版。
**边界**：不改变 RAG 策略、评测结果、信源状态机或服务边界；不把历史实验写成实时监控；
不为了简历引入新中间件；公开截图不得包含邮箱、令牌、密钥或浏览器隐私信息。
**完成标准**：`/eval` 首屏能说明快照日期、模型/语料变化后的重评流程与实时运行入口；
信源后台能说明数据读取与页面刷新语义；README 30 秒内可理解项目价值与架构；面试材料覆盖
业务、采集、数据、RAG、后端、前端、部署、安全、权衡与追问；Web typecheck/lint/unit/build、
Docker 页面 smoke 与 Chrome 桌面/移动端视觉验收通过。
**当前证据**：`docs/status/portfolio-closeout-20260812.md`、`docs/interview/README.md`、
`docs/assets/screenshots/`；Web 73/73、typecheck、lint、production build 与 Docker HTTP smoke 通过。

## 4. AI IDE 统一提示词

将以下提示词与本目录一并交给任一 AI IDE：

```text
你正在开发 AI Hot Radar。先完整阅读 README.md、00-master-spec.md，
再阅读当前任务对应的专项文档和 config。先检查仓库现状，不要假设尚未存在的代码。

本次只执行任务卡：<TASK-ID>。
请先输出：1) 需求理解；2) 将修改的文件；3) 验收命令；4) 风险。
随后直接实现、运行测试并修复，直到满足 Definition of Done。

不得静默改变已锁定技术决策，不得扩大到后续里程碑，不得用 mock 代替任务要求的
真实信源验收。发现规格冲突时停止实现并指出文档 ID 和冲突位置。
最终汇报：完成项、关键设计、测试证据、未完成/风险、建议的下一张任务卡。
```

## 5. 代码审查清单

- 是否引入了文档未授权的新基础设施？
- 是否保持 Java/Python 契约一致？
- 是否有状态推进但无幂等/版本检查？
- 是否把 Redis 当事实源或把正文塞进消息？
- 是否将 LLM 自由文本直接信任入库？
- 是否把文章重复和事件相同混淆？
- 是否引用 AI 摘要而非原始 passage？
- 是否为外部请求设置超时、重试、host 限速和 SSRF 防护？
- 是否同步迁移、契约、测试和文档？
- 是否保留用户已有改动，避免无关重构？

## 6. 变更管理

新增 `docs/adr/NNNN-title.md`，格式：背景、决策、备选、后果、回滚、日期。以下变化必须 ADR：数据库/队列/搜索引擎、服务拆分、身份认证、RAG 检索策略、核心数据实体、公开 API 破坏性变更。

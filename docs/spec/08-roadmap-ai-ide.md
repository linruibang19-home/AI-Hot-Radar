# 08｜开发路线与 AI IDE 执行规范

文档 ID：`AHR-ROADMAP-800`

## 1. 执行原则

Codex、Claude Code、Cursor 使用同一套规格，不为不同工具维护互相冲突的需求。根目录
`AGENTS.md` 是唯一、工具无关的执行约束入口；各工具直接读取它，不再跟踪额外指针文件。

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

**状态**：✅ 2026-08-11 完成；验收记录见 `docs/status/current/project-status.md` §0。
**读取**：`07-quality-security-ops.md`、`11-end-to-end-runbook.md`、
`12-delivery-index.md`、`docs/status/current/project-status.md`。
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
`docs/status/product/rag-specialist-audit-20260811.md`。Planner 的 query-type 代理经扫描确认
在当前语料上不可操作，未用默认关闭的 LLM 结果冒充线上门禁通过。
**读取**：`04-rag-agent-design.md`、`07-quality-security-ops.md`、
`docs/archive/development/m4-rag-evaluation.md`、`data/golden/README.md`、
`docs/status/product/rag-product-readiness-20260810.md`。
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
`docs/status/product/rag-security-performance-20260811.md`。
**读取**：`04-rag-agent-design.md`、`07-quality-security-ops.md`、
`docs/status/product/rag-product-readiness-20260810.md`、ADR-0017、ADR-0023、ADR-0024。
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
`docs/status/product/rag-ui-polish-20260811.md`。
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
`docs/status/history/handoff-20260811.md`。
**读取**：`README.md`、`12-delivery-index.md`、`docs/status/current/project-status.md`、
`docs/status/history/handoff-20260810.md` 以及 08-11 三份 RAG 验收记录。
**输入**：当前 Git 分支/提交、Docker Compose 运行态、数据库实测快照与本轮门禁结果。
**产出**：更新总入口、交付索引、累计项目状态和新的当前交接文档；旧交接保留为历史记录。
**完成标准**：当前分支、数据量、测试数、RAG 门禁、报告状态和剩余任务在各入口口径一致；
不把服务器权限事项、人工视觉验收或未来产品化能力写成已完成。

### TASK-M5-002｜报告阅读体验与结构化只读模型

**状态**：🟡 2026-08-11 实现与自动化验收完成，Chrome 视觉门禁待补；证据见
`docs/status/product/report-reader-20260811.md`。
**读取**：`01-product-requirements.md`、`06-frontend-spec.md`、
`docs/status/history/handoff-20260811.md`。
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
`docs/status/product/report-publication-20260811.md`。
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
**当前证据**：ADR-0026、Flyway V023、`docs/status/product/report-subscriptions-20260811.md`。
Core API 持有双重确认、订阅与投递事实，Web 只做代理和交互；本地 Mailpit 已实测申请、确认、
PUBLISHED 投递、在线阅读链接与退订，验收数据随后清理。

### TASK-M5-005｜生产部署预检与恢复门禁

**状态**：✅ 2026-08-11 完成；所有不依赖目标服务器的上线准备与本地真实恢复演练通过。
**读取**：`02-system-architecture.md`、`07-quality-security-ops.md`、
`11-end-to-end-runbook.md`、`docs/design/current/m5-deployment.md`、
`docs/design/current/m5-first-deploy-checklist.md`。
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
`docs/status/delivery/production-deployment-20260811.md`，当前交接见
`docs/status/current/handoff-20260814.md`。
**读取**：`02-system-architecture.md`、`07-quality-security-ops.md`、
`11-end-to-end-runbook.md`、`docs/design/current/m5-deployment.md`、
`docs/design/current/m5-first-deploy-checklist.md`、TASK-M5-005 验收记录。
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
`docs/status/product/generation-model-selection-20260811.md`。
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
`docs/status/product/rag-operations-ui-20260811.md`。
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
**当前证据**：`docs/status/product/v016-selection-email-20260812.md`；生产当天 12 条精选已分布到
8 个来源族，arXiv 仅 2 条；1 个日报订阅已显式确认，下一期开始投递。

### TASK-M5-010｜工程数据时效语义与作品集封版

**状态**：✅ 2026-08-12 完成；代码、脱敏截图与面试材料已通过本地门禁，等待发布验收。
**读取**：`06-frontend-spec.md`、`07-quality-security-ops.md`、TASK-M5-008、
TASK-M5-009、`docs/status/current/handoff-20260814.md`。
**输入**：现有 `/eval` 版本化评测摘要、动态信源健康数据、生产页面与发布证据。
**产出**：明确区分静态发布评测与动态运行状态；为信源后台提供可理解的刷新时间语义；
用脱敏生产截图、分层 README 与面试学习材料完成公开作品集封版。
**边界**：不改变 RAG 策略、评测结果、信源状态机或服务边界；不把历史实验写成实时监控；
不为了简历引入新中间件；公开截图不得包含邮箱、令牌、密钥或浏览器隐私信息。
**完成标准**：`/eval` 首屏能说明快照日期、模型/语料变化后的重评流程与实时运行入口；
信源后台能说明数据读取与页面刷新语义；README 30 秒内可理解项目价值与架构；面试材料覆盖
业务、采集、数据、RAG、后端、前端、部署、安全、权衡与追问；Web typecheck/lint/unit/build、
Docker 页面 smoke 与 Chrome 桌面/移动端视觉验收通过。
**当前证据**：`docs/status/delivery/portfolio-closeout-20260812.md`、`docs/interview/README.md`、
`docs/assets/screenshots/`；Web 73/73、typecheck、lint、production build 与 Docker HTTP smoke 通过。

### TASK-M5-011｜作品集叙事补全与腾讯云迁移基线

**状态**：✅ 2026-08-12 完成；纯文档与迁移基线经 PR #12 / GitHub CI 验证。
**读取**：`00-master-spec.md`、`02-system-architecture.md`、`03-data-ingestion.md`、
`04-rag-agent-design.md`、`06-frontend-spec.md`、`07-quality-security-ops.md`、
`11-end-to-end-runbook.md`、TASK-M5-010 与 `docs/status/current/handoff-20260814.md`。
**输入**：已上线的 M0–M5 产品、五张脱敏截图、固定 RAG 发布评测、生产运行证据，
以及待购买的广州 2C4G5M / 60GB Ubuntu 24.04 Docker 轻量应用服务器。
**产出**：把根 README 重排为 30 秒、3 分钟、30 分钟三层阅读入口；按业务架构、采集与
数据模型、RAG、后端一致性、前端、部署安全、题库、简历 STAR、白板与演示拆成
`docs/interview/00`–`10` 十一份独立材料；记录新服务器兼容性、备案前平行迁移、DNS 回切
与容量边界。
**边界**：不修改 RAG 策略、服务边界、数据库、API 或生产运行提交；不把静态评测写成
实时监控；不把动态生产计数写成无日期的长期承诺；不在截图、README 或迁移文档中记录
邮箱、令牌、口令与服务器管理凭据；本卡不代替主人购买实例或提交 ICP 备案。
**完成标准**：README 能分别支持 30 秒扫读、3 分钟架构理解与 30 分钟技术深挖；11 份
面试材料各自回答一个稳定主题且没有并行重复版本；所有相对链接、图片、敏感串扫描与
仓库文档门禁通过；分支经 PR/CI 合入 `main`，并明确本次纯文档变更不触发生产部署。
**当前证据**：`docs/status/delivery/portfolio-interview-completion-20260812.md`、
`docs/status/operations/tencent-cloud-migration-readiness-20260812.md`、`docs/interview/README.md`。

### TASK-M5-012｜Docker 磁盘增长边界

**状态**：✅ 2026-08-12 完成；本卡只约束本地与生产 Docker 存储增长，不改变业务行为。
**读取**：`07-quality-security-ops.md`、TASK-M5-005、TASK-M5-011 与当前 Compose。
**输入**：本地 Docker Desktop 曾累计 45.02GB 镜像、24.74GB BuildKit 缓存和 7.66GB 卷；
运行容器可写层不足 1MB，确认增长来自历史构建产物而非业务数据库。
**产出**：所有 Compose 服务使用压缩轮转的 `local` 日志驱动，每容器最多 3 个 10MB 日志；
Windows 维护脚本把 BuildKit 缓存限制在 5GB，并删除七天以上且未被容器引用的镜像；计划任务
每日执行，明确永不自动 prune volume。
**边界**：不删除 PostgreSQL/Redis 挂载卷，不停止当前生产，不让生产主机本地构建业务镜像；
宿主 VHDX 收缩仍是需要停 Docker Desktop 的独立维护窗口。
**完成标准**：本地/生产 Compose 可渲染；生产所有服务具有相同的有界日志配置；维护脚本在
Docker 运行和未运行时均安全；重建本地容器后实际日志驱动为 `local`；PostgreSQL/Redis 及
项目健康检查通过。
**当前证据**：`docs/status/operations/docker-storage-controls-20260812.md`。

### TASK-M5-013｜仓库卫生、证据归档与代码学习地图

**状态**：✅ 2026-08-12 完成；只整理可再生产物和知识入口，不改变业务行为。
**读取**：`00-master-spec.md`、`07-quality-security-ops.md`、`12-delivery-index.md`、
TASK-M5-011、TASK-M5-012 与当前全部受 Git 管理文件。
**输入**：482 个受 Git 管理文件、83 份 `docs/status/` 文件、两个历史工具 worktree、
本地构建缓存、工作区恢复备份及已验证的 Windows 异机备份任务。
**产出**：清理明确可再生的缓存和已合并 worktree；保留未提交用户改动为可恢复 stash；
工作区备份仅在同名、同大小、同 SHA-256 异机副本存在后删除；补齐代码全景图、状态证据索引、
仓库卫生验收和文档导航；防止临时挂载目录再次进入工作区。
**边界**：不执行 `git clean -xdf`，不删除 `.env`、依赖目录、PostgreSQL/Redis 卷、黄金集、
评测 JSON 或唯一备份；不移动已有证据文件，不修改服务边界、RAG 策略、数据库/API 和生产机；
不把历史快照改写成当前状态。
**完成标准**：所有源码、迁移、配置、基础设施和文档都有可追踪入口；Git 跟踪文件无临时名、
重复内容或敏感串；Markdown 相对链接、规格、Python、Java、Web、Compose 与 Flyway 门禁通过；
整理 PR 经 CI 合入 `main`，生产版本差异被明确记录。
**当前证据**：`docs/status/operations/repository-hygiene-20260812.md`、`docs/code-map.md` 与
`docs/status/README.md`；PR #14 的最终 GitHub Actions run `31610709745` 已在干净的
JDK 21/Node/Python/PostgreSQL 环境通过 Spec、AI service、Core API、Web 与 Flyway 五组门禁。

### TASK-M5-014｜实现事实校准、工程手册与面试教材重构

**状态**：✅ 2026-08-13 完成；只校准实现事实、重构知识入口并增加文档门禁，不改变运行行为。
**读取**：`00-master-spec.md`、`02-system-architecture.md`、`03-data-ingestion.md`、
`04-rag-agent-design.md`、`10-source-adapter-implementation.md`、`11-end-to-end-runbook.md`、
全部 ADR、核心代码入口与现有 `docs/interview/`。
**输入**：当前代码/Compose/Flyway 实现、M0–M5 历史证据，以及现有面试材料过度压缩、
Outbox/调度/证据物理表表述漂移的审计结果。
**产出**：先以 ADR-0028/0029 固定当前任务编排和证据物理模型，再建立按业务链路、运行
架构、数据状态、采集、内容、报告邮件、RAG、三端实现、部署运维和工程权衡组织的工程手册；
面试材料扩展为分层口述、代码走读、100+ 题库、STAR、白板、演示和学习计划；建立文档
分级、历史冻结和自动链接/事实校验。
**边界**：不改变业务代码、数据库、API、RAG 策略或生产运行版本；不删除历史负结果；
不把目标架构、预留表、动态生产计数或历史评测写成当前实时事实。
**完成标准**：规格与当前实现不再冲突；工程手册可独立完成全链路学习；面试材料支持
30 秒到 30 分钟分层表达及代码证据追问；Markdown 链接、规格、敏感串与相关代码测试通过；
PR/CI 合入 `main`，纯文档变更不触发生产部署。

### TASK-M3-REOPEN-001｜Story 公开入口有效性收口

**状态**：✅ 2026-08-13 完成；验收记录见
`docs/status/product/story-public-experience-20260813.md`。本卡只收口公开阅读体验，不重写聚类身份或算法。
**读取**：`00-master-spec.md`、`01-product-requirements.md`、`03-data-ingestion.md`、
`06-frontend-spec.md`、M3 里程碑与 `docs/handbook/06-content-story-selection.md`。
**输入**：本地 1693 个 Story 中只有 39 个达到至少两家独立信源；现有列表仍将 Story 表达为
另一份资讯流，详情暴露内部相似度，却没有直接显示参与来源与阅读目的。
**产出**：公开入口改为“事件追踪”，只展示至少两家独立信源且最低聚类置信度不低于
`0.67` 的事件；列表读模型返回参与来源名称，卡片直接说明来源构成；详情以主来源摘要和
来源时间线组织阅读，不再向普通读者展示内部聚类相似度；同步 OpenAPI、测试和验收证据。
**边界**：不删除 `story`/`story_item`，不改变精选、报告或 RAG 的 Story 折叠；不在本卡修改
聚类合并阈值、全量重建策略、Story 稳定身份、组织母体归一化或 486 条待复核建议；公开读取
可使用更严格的置信度门槛；不把多方报道表述为事实已经得到独立证实。
**完成标准**：公共列表查询始终只返回 `independent_source_count >= 2` 且最低置信度达到
`0.67` 的事件；列表和详情均可看到具体来源；详情不显示算法相似度；Java、Web、Python
Story/报告/RAG 回归、生产构建与 Docker 页面冒烟通过。

### TASK-M5-015｜主题地图关联质量与可解释导航

**状态**：✅ 2026-08-13 实现与克隆语料验收完成；只修正主题/厂商导航语义，未改变 RAG 检索策略。
**读取**：`00-master-spec.md`、`01-product-requirements.md`、`03-data-ingestion.md`、
`06-frontend-spec.md`、ADR-0030 与 `config/taxonomy.yaml`。
**输入**：厂商页把 `subject/object/mention` 等价收录、详情 40 条被误写为总数、主题关联无
公共展示门槛、重新加工不移除旧关联；2026-08-13 本地 OpenAI 关联样本中仅 39.9% 为主体，
45.0% 为顺带提及。
**产出**：以版本化 `item_vendor_relation` 保存核心/相关/提及关系和原因；成功加工时原子替换
实体与主题关联；增加厂商游标 feed、真实计数、近七日计数和匹配解释；公共主题只使用置信度
达标且每篇前三的关联；前端保持现有信息密度并增加关系分层和更新时间。
**边界**：不删除 `item_entity` 弱提及事实，不新增 LLM 调用、搜索引擎、消息中间件或图数据库；
不改变 RAG、Story、精选和报告策略；旧厂商数组 API 在弃用周期内保留。
**完成标准**：历史和新增内容使用同一关系规则；厂商默认页不再混入纯 mention；卡片与详情
总数一致且支持分页；每条内容可解释命中原因；Python、Java、Web、Flyway、Compose 与页面
视觉回归通过，并保存主题地图质量基线与剩余召回风险。

### TASK-M5-016｜主题地图关系黄金集与回归门禁

**状态**：🟡 2026-08-13 工程阶段完成；真实快照抽样、双人盲审、独立裁决、脱敏归档与严格
校验工具已通过，1995 条候选等待真实人工复核，不能把待复核状态写成分类质量已达标。
**读取**：`00-master-spec.md`、`01-product-requirements.md`、`03-data-ingestion.md`、
`06-frontend-spec.md`、ADR-0030、TASK-M5-015 与 `data/golden/topic-map/README.md`。
**输入**：V025 已让厂商关系和公共主题投影可解释，但当前规则仍由阈值与启发式产生；没有独立
人工标签时，只能证明关系可重放，不能证明 403 条 OpenAI 内容或 73 条 RAG 内容真的相关。
**产出**：按每个厂商的 `primary/related/mention/unmatched` 和每个主题的
`public/suppressed/unmatched` 确定性抽样；候选绑定原始正文 revision/hash；校验完整分层、
样本不足、重复关系与审核元数据；全部人工复核前拒绝输出效果指标；复核后按分层总体规模计算
厂商核心精度、公开关系 precision/recall 与主题 precision/recall。
**边界**：第一阶段不改 V025 分类器、不调用 LLM 自动标注、不把第三方正文候选队列提交到公开
仓库、不预设看过结果才决定的数值门槛；第二阶段由人工完成标签和争议复核，再预注册 v2 目标。
**完成标准**：`topic-quality sample` 在同一 MVCC 快照生成稳定候选；`validate` 能识别空分层、
样本量、重复、revision 与审核元数据错误；存在待审核样本时 `evaluate` 非零退出且不输出部分
准确率；双人盲审不得暴露生产预测，分歧必须由独立第三人裁决；人工集完成后保存脱敏标签、
加权基线与分层 bootstrap 95% 置信区间，再决定是否进入关系分类器 v2。

**作品集收口**：⏸ 2026-08-13 明确省略真实双人盲审与第三人裁决。工程抽样、隐藏预测、
revision/hash 绑定、严格校验和评估工具保留，但不输出人工 precision/recall，也不把 1,995 条
待审核候选写成准确率。团队化执行流程与面试边界见 `docs/interview/03-rag-deep-dive.md`。

### TASK-M5-017｜主题时间线正确性、感知性能与 RAG 语料实证收口

**状态**：✅ 2026-08-13 完成。PR #17/版本 v0.1.9 已发布；生产厂商 feed 日期单调倒序，
主题页热缓存 TTFB 约 0.20–0.35 秒，Chrome 导航/忙碌反馈门通过；原文语料门随 TASK-M5-018
在 v0.1.10 完成最终验收。
**读取**：TASK-M5-015/016、`06-frontend-spec.md`、`04-rag-agent-design.md`、ADR-0029/0030、
厂商 feed、Web 时间线、chunker/backfill 与生产只读快照。
**输入**：厂商相关页按 relation score 优先导致 5/8 月日期交错；全屏加载 portal 放大约 0.2 秒
导航等待；2,098 篇当前非空正文中 2,095 篇已切，7,912 个当前块全部向量化，但 14 个旧块因
无换行超长正文超过 1,200-token 硬上限。
**产出**：厂商 cursor 时间优先；Web 时间倒序不变量；metadata/page 请求去重；保留旧页面的
轻量 pending 导航；单行超长安全切分与 `rechunk --oversized-only`；生产原文切块/向量审计；
把人工复核未执行的边界和 RAG 原文证据写入面试材料。
**边界**：不改 V025 关系分类规则，不改 RAG 检索策略/模型/核心实体，不引入新缓存或基础设施，
不伪造人工标签；只重切超过当前硬上限的 current revision，随后幂等补其向量。
**完成标准**：厂商 feed 日期单调倒序且 cursor 不重不漏；Web 打乱输入仍按时间展示；当前
revision 无 >1200 token chunk、全部非空正文有块、全部 current chunk 有 bge-m3 向量；Java、
Python、Web、CI、生产 smoke 与浏览器视觉回归通过。
**证据**：`docs/status/product/topic-timeline-performance-20260813.md`、
`docs/status/product/rag-corpus-audit-20260813.md`。

### TASK-M5-018｜引用安全的不可变分块集

**状态**：✅ 2026-08-13 完成。PR #18/版本 v0.1.10 已发布到生产；V026、定向重切、增量
Embedding、SQL/HTTP/Chrome、备份恢复演练全部通过。该卡由 TASK-M5-017 的生产重切外键
保护现场触发。
**读取**：`04-rag-agent-design.md`、ADR-0016/0029/0031、TASK-M5-017、V001/V026、
chunker/backfill/retrieval/parent 与 citation 查询。
**输入**：旧 `chunk_revision` 先删除同 revision 的块；生产中已有块被 `rag_citation` 引用，外键
拒绝删除并使事务安全回滚。删除引用或原地覆盖都会破坏历史答案的可复核性。
**产出**：Flyway 为 chunk 增加不可变 `chunk_set_id` 和唯一 active set；重切退役旧 set 后插入
新 set；检索、Embedding、评测和当前语料指标仅读 active；历史引用继续读 retired；parent 仅在
同 set 展开；补充生产故障、生命周期与人审边界的面试材料。
**边界**：不改正文 revision、不级联删除 citation、不切换 embedding/reranker/生成模型、不改变
召回融合策略；本卡不物理清理 retired evidence。
**完成标准**：V026 空库和升级迁移通过；已引用块可安全重切；active revision/ordinal 唯一；
所有在线召回和向量回填排除 retired；历史引用与父块仍可解析；TASK-M5-017 的 14 个超限 active
块归零并补齐向量；CI、发布、生产 SQL/HTTP/浏览器验收通过。

**生产证据**：13 个受影响 revision 从 80 个旧 active 块生成 107 个新 active 块；107/107 使用
`BAAI/bge-m3` 增量向量化且 remaining=0；当前超限块、缺向量、active 序号重复、chunk 等于
`summary_zh` 均为 0；3 个 retired chunk 仍被历史引用并可解析。迁移后备份 132MB，隔离恢复
快照为 `140|2215|9121|1788|17|026`。一个 18 字符且仍为 `DISCOVERED` 的包版本事件尚未进入
正文处理阶段，不计为 RAG 漏切。

### TASK-M5-019｜业务深挖教材、工作区清洁与分层容量基线

**状态**：✅ 2026-08-14 完成；本卡只补可复现的工程证据和学习材料，未改变业务架构、
RAG 检索策略或生产容量。
**读取**：`00-master-spec.md`、`02-system-architecture.md`、`03-data-ingestion.md`、
`04-rag-agent-design.md`、`07-quality-security-ops.md`、TASK-M5-014/017/018、全部当前 handbook、
interview、Prompt、评分、缓存和服务入口代码。
**输入**：当前 README 版本/迁移/动态数字已经落后于 v0.1.11/V026；业务教材尚未集中解释
LLM 调用、Prompt、推荐排序、阈值、Agent/记忆边界和失败案例；本地存在测试、类型检查与构建
产生的可再生缓存；项目缺少隔离第三方模型成本的分层压测脚本和诚实容量口径。
**产出**：校准 README 当前事实；按采集、内容加工/推荐、报告邮件、RAG 离线/在线、评测与
交付六条主线扩写 handbook/interview；新增 LLM/Prompt/阈值与 Agent 编排专题；提供默认 dry-run
的跨平台缓存清理工具；使用本地 Docker Compose 与 k6 建立 Web/Core API/AI 本地检索、缓存
冷热和受控外部模型路径的分层负载模型，保存环境、命令、延迟、吞吐、资源和限制。
**边界**：不压测公共生产域名，不在并发测试中消耗真实 LLM/Embedding 额度；不删除 `.env`、
`.venv`、`node_modules`、数据库卷、黄金集、fixture、评测证据或唯一备份；不为了简历引入
LangChain/LangGraph、Kafka、Elasticsearch、Kubernetes 或新运行时中间件；框架比较只记录
当前选择、触发条件和迁移代价。
**完成标准**：缓存清理只命中 allowlist 且二次运行幂等；负载脚本可在干净开发机复现，至少
覆盖 Core API 读路径、Web SSR/代理、AI 本地 RAG 统计/数据库控制路径；报告同时
给出吞吐、p50/p95/p99、错误率、容器 CPU/内存、数据库/Redis/线程池观察和冷热语义，不能把
本地开发机结果包装成 2C4G 生产 SLA；文档代码路径、阈值、Prompt 和实现状态经自动校验，
Python/Java/Web/Compose 相关门禁通过。

### TASK-M5-020｜RAG 统计聚合性能与 2C4G 容量验收

**状态**：✅ 2026-08-14 修复、CI、香港 2C4G 低风险生产验证完成；隔离同规格寻顶/soak 作为容量规划后续项。
**输入**：TASK-M5-019 的真实 `/rag/stats` 基线在 20 VU 下 p95 918.94 ms，越过 750 ms 初始门；
当前开发机结果不能外推生产容量。
**目标**：profile `retrieval_summary` 聚合 SQL 与序列化，先以查询/索引或短 TTL 可失效缓存降低
统计页长尾；在脱敏生产副本、相同镜像 SHA 和 2C4G 限额上完成冷/热阶梯、恒定到达率与 soak，
形成满足 SLO 的最高稳定容量和 30% 余量。
**边界**：不压公共生产域名，不调用真实 LLM/Embedding/reranker 做并发压测，不用调大门限掩盖
失败，不因单机基线提前引入 Kafka/Kubernetes/独立向量库。
**实现记录（2026-08-14）**：SQL 单独压测约 1,080 TPS/9.26 ms，确认根因是 async route 内同步
psycopg 与并发重复聚合；改为 `asyncio.to_thread`、按窗口进程内 single-flight、Redis 30 秒可失效
快照。相同本地 20 VU 复测 AI P95/P99 从 837.99/4046.49 ms 降至 11.21/18.77 ms，整轮
15,536 请求、154.91 req/s、0 错误。生产脚本只跑 1→2→5 VU、只读内部路径、pgbench 和 Redis
观察；真正容量结论仍必须等隔离 2C4G 阶梯与 soak。

**生产证据（2026-08-14）**：同 SHA 的 10 个容器健康，1→2→5 VU 内部混合读完成 1536 请求、
25.09 req/s、0 错误；AI/Core/Web P95 分别为 10.69/96.82/644.09 ms。pgbench 内容流/RAG
统计为 741.02/79.43 TPS 且 0 失败；Redis PING 为 40.4k–45.4k req/s、0 eviction。该轮是
低风险发布验证，不是容量寻顶，详见 `docs/status/loadtest/2026-08-14-m5-020-production.md`。

### TASK-M5-021｜后端域内分层、运行参数与作品集说明收口

**状态**：✅ 2026-08-14 已由 PR #22 合并并发布 `v0.1.14@2ba1222`；公开 API、数据库和
RAG 策略未变。
**读取**：`00-master-spec.md`、`02-system-architecture.md`、TASK-M5-019/020、Core API 与 AI
Service 全部入口、当前生产 Compose/JVM 只读事实。
**输入**：Core API 虽按 `content/subscription/admin` 分域，但 Story/Report/Source Controller 中仍有
直接 JDBC 或查询/聚合职责，仓库浏览时难以看清 transport/application/persistence 边界；Python
虽已按 ingestion/processing/rag 分域，缺少自动门禁防止 FastAPI 渗入领域层；README 的生产版本、
测试数和 JVM 说明落后，Compose 注释错误地把 512 MiB 的 75% 描述为 480 MB heap。
**产出**：Story/Report 拆出 Service 与 Repository，Source SQL 收口 Repository；ArchUnit 禁止
Controller 直接依赖 JDBC；Python AST 测试约束 FastAPI 与领域依赖方向；两端模块 README、工程
手册、面试专项、代码地图和根 README 说明 package-by-feature/域内分层、JDBC 非 JPA 取舍、实际
JVM/容器预算、Redis 缓存/限流语义与腾讯云备案迁移边界。
**边界**：不改数据库、公开 API、服务边界、RAG 检索、邮件状态机或 Redis 事实语义；不为了目录
外观引入 JPA、LangChain/LangGraph 或全局四层包；腾讯云广州机不写成当前生产环境。
**完成标准**：Java 21 全量 test/verify、Python pytest/mypy/ruff/format、文档链接和生产 Compose
静态门禁通过；Controller→JDBC 与 FastAPI 领域渗透的回归测试可复现；动态 JVM 数字标注日期。
**发布证据**：主分支 CI 与 tag Release 全绿，GHCR 三镜像均由同一 40 位 SHA 构建；香港
`production`、`IMAGE_TAG` 与三镜像已对齐 `2ba12225e25e9ed7efe7e116928293b0d535f2a7`，10 个
容器健康，公开 smoke 通过。部署后生成并校验 143 MiB 备份，隔离恢复得到
`140|2358|9735|1919|17|026`（source/content/chunk/story/report/Flyway），恢复库按守卫规则清理。

### TASK-M5-022｜作品集仓库入口与 README 信息架构收口

**状态**：✅ 2026-08-14 完成；仅整理仓库入口与作品集说明，不改变运行行为。
**读取**：`00-master-spec.md`、`02-system-architecture.md`、TASK-M5-019/021、根目录规则入口与
README 当前首屏。
**输入**：根目录同时跟踪 `AGENTS.md`、`CLAUDE.md` 与 Cursor 规则指针，内容虽以转发为主，
仍增加首次浏览噪声和规则再次漂移的可能；README 的业务、服务和 RAG Mermaid 图横向分支过多，
GitHub 预览需要缩放后才能理解，缺少一张解释根目录为何存在的阅读地图。
**产出**：以工具无关的 `AGENTS.md` 作为唯一工程规则入口，移除 Claude/Cursor 重复指针；保留并
解释 Flyway migrations、契约、配置、CI 与交付目录；把 README 的业务链路、运行拓扑和 RAG
链路改为无需缩放的分层文本图，补充面试官 30 秒/3 分钟/深入阅读路径与根目录地图。
**边界**：不删除 migrations、fixtures、黄金集、规格、ADR、CI 或部署资产；不改数据库、API、
服务边界、RAG 策略和生产镜像；历史状态文档不重写，只修当前规范中的活动入口。
**完成标准**：README 不再依赖 Mermaid 才能理解三条主线；仓库根目录每个一级入口都有用途；
当前规范不再要求已删除的工具专用指针；文档/规格校验与 `git diff --check` 通过。
**验证证据**：`validate_spec.py`、`validate_docs.py`、Ruff 与 `git diff --check` 通过；README 中
业务、服务和 RAG 三条主线均为纯文本图，根目录不再跟踪 `CLAUDE.md` 或 Cursor rule，Flyway
V001–V026、契约、CI、部署与评测证据保持不变。

### TASK-M5-023｜README 证据优先分层与公开阅读体验

**状态**：✅ 2026-08-14 完成；只调整公开项目入口，不改变运行行为。
**读取**：`00-master-spec.md`、`01-product-requirements.md`、`02-system-architecture.md`、
TASK-M5-019/021/022、当前 README、handbook/interview/status 导航。
**输入**：README 首屏仍被生产数字占用，RAG 截图折叠过深；仓库地图标题直接写“面试官”，
暴露内部使用目的；工程亮点未从功能清单中独立出来；文档导航长表不利于分层阅读。
**产出**：首屏只保留定位、Live Demo、紧凑技术栈、首页与 RAG 两张主图；把带日期的生产和
评测数字折叠为非实时快照；按 30 秒、3 分钟、30 分钟按需、本地运行、验证、边界和分层文档
导航重写；仓库地图使用中性标题并解释代码、迁移、契约、配置、交付与证据目录的职责；新增
5–7 条决策型工程亮点。
**边界**：不编造用户量、指标和功能；不更新生产镜像或服务器；不改变 API、数据库、RAG、
邮件和服务边界；根 README 不复制 handbook/status 的全部实现细节。
**完成标准**：两张关键截图在首屏直接可见；所有数字都有日期、样本量或非实时说明；三条 text
架构图无需 Mermaid；导航分为必读、深入、项目讲解与面试准备；规格/文档/链接/Ruff 和
`git diff --check` 通过。
**证据**：README 首屏直接显示 `home.png` 与 `rag-answer.png`；仓库地图已改为中性的“代码与
证据如何组织”；`python scripts/validate_docs.py` 检查 136 份 Markdown / 322 个本地链接，
`python scripts/validate_spec.py`、`python -m ruff check scripts` 与 `git diff --check` 均通过。

### TASK-M5-024｜公开动态中文阅读就绪门禁

**状态**：✅ 2026-08-15 本地修复与实库回归完成，按要求暂不提交、推送或部署。
**读取**：`01-product-requirements.md`、`09-source-registry-fulltext.md`、
`10-source-adapter-implementation.md` 与当前采集/结构化流水线。
**输入**：采集每 120 秒入库、LLM 流水线每 900 秒结构化，两者之间的 `PENDING` 窗口被
`/items` 直接展示；`SKIPPED` 记录还会永久退回英文原题，GitHub/RSS excerpt 中的 HTML 与
Markdown 因而以文本形式露出。生产抽查确认同一批记录在后续 `ENRICHED` 后已有正确中文字段。
**产出**：公开 feed、日期导航与分类计数统一只读取 `ENRICHED` 且中文标题/摘要完整的记录；
入库总数与后台状态仍保留全部候选；Web 卡片增加第三方 HTML/Markdown 纯文本化的防御边界。
**边界**：不删除或改写原文/候选记录，不改变详情页的原始证据能力，不缩短处理间隔，不把
Redis 变成状态源；是否发布以本地回归与用户确认后的独立提交为准。
**完成标准**：SQL 门禁测试、Web 纯文本清洗测试、Java/Web 全量相关门禁与本地浏览器回归通过；
最新 `PENDING/SKIPPED` 不再出现在公开列表，完成结构化后自动进入列表。
**验证**：Java 21 容器 `mvn -B verify` 85/85；Web `typecheck`、`lint`、`test`（81/81）与
生产构建通过；本地 PostgreSQL 存在 196 条 `PENDING`、88 条 `SKIPPED`，临时挂载新 JAR 的
Core API 实测前 8 条全部为中文字段完整的 `ENRICHED`，未改动原始候选数据。

### TASK-M5-025｜证据入库、Redis 与 RAG 质量教材收口

**状态**：🟡 2026-08-15 实现与本地全量回归完成，等待 CI 与生产发布证据。
**读取**：`03-data-ingestion.md`、`04-rag-agent-design.md`、`09-source-registry-fulltext.md`、
`10-source-adapter-implementation.md`、ADR-0005/0015/0029/0031，以及当前 ingestion、chunking、
RAG cache/eval、Java CacheConfig 和 Flyway 代码。
**输入**：现有教材分别介绍采集、RAG 与 Redis，但没有把不同 profile 的发现载荷、全文来源、
数据库行、实际切块形态、图片/PDF 边界、全部 Redis key/TTL，以及 90 题到 `/eval` 静态快照的
生成过程放在同一组可核验专题中；TASK-M5-023 的中文公共阅读门也尚未发布。
**产出**：不同信源到 `raw_document/item/revision/chunk/citation` 的字段与样例；400/120/700/
60/1200 切块规则、不可变 chunk set 与多模态边界；Java/Python Redis key、TTL、失效、限流和
PostgreSQL fallback；六类 90 题、schema、指标、B2/B8/GEN-FIX、质量页刷新与发布门；完成
TASK-M5-023 的提交、CI、不可变镜像和生产 smoke。
**边界**：不把本地 2026-08-15 动态样本写成生产承诺；不宣称图片 OCR/视觉 RAG、PDF 版面引用、
报告 Redis cache、outbox 消费者或实时 `/eval` 已实现；不改变 RAG 策略、核心实体或数据库。
**完成标准**：三份专题可从 README/handbook/interview 导航到达；命令、TTL、字段、样例和当前
边界与代码一致；文档校验、Python/Java/Web 全量门禁、GitHub CI/Release、香港生产部署与公网
内容/RAG/运行页 smoke 通过。

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

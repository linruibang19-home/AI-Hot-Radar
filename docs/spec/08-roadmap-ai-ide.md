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

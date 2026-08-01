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

**读取**：`docs/03-data-ingestion.md`、`docs/09-source-registry-fulltext.md`、`config/sources.yaml`、`config/social-watchlist.yaml`。  
**产出**：Flyway 表、source loader、adapter、cursor、fixture、集成测试。  
**关键测试**：同 feed 重放、更新条目、缺失 guid、文章回源、正文质量门禁、304、429、超时、非法 URL。

### TASK-M1-002｜全文回源与信源健康门禁

**读取**：`docs/09-source-registry-fulltext.md`、`docs/07-quality-security-ops.md`。  
**产出**：profile adapter、站点 fixture、正文质量评分、CONFIGURED/PROBING/ACTIVE/DEGRADED/QUARANTINED 状态机、`source-health.json`。  
**完成标准**：不得把 RSS/搜索摘要计入全文；Wave A 20 个来源最新 3 篇中至少 2 篇正文合格；失败来源自动降级且保留原因。

### TASK-M1-003｜GitHub、Changelog、arXiv 与公开 API

**读取**：`docs/10-source-adapter-implementation.md`、`config/ingestion-profiles.yaml`、`config/site-overrides.yaml`。  
**产出**：GitHub Releases 分页/限额 Adapter、Changelog revision diff、arXiv HTML/PDF、Hugging Face model card、OpenAlex 元数据 Adapter。  
**关键测试**：GitHub Link 分页/ETag/空 body，Changelog heading 更新，arXiv HTML 缺失转 PDF，模型卡 404，OpenAlex cursor；所有 fixture 均可离线重放。  
**完成标准**：每类至少 2 个真实 canary（OpenAlex 1 个即可），原始响应、字段映射、游标与错误分类可追溯。

### TASK-M2-001｜内容加工契约

**产出**：Pydantic schema、JSON Schema、Java generated DTO、Prompt v1、失败修复一次、dead-letter。  
**禁止**：解析失败时把自由文本直接写进结构化列。

### TASK-M4-001｜RAG 检索基线

**产出**：黄金集、SQL/FTS baseline、Vector baseline、RRF、离线报告。  
**顺序**：先测 baseline，再加 reranker；不得只展示几个主观示例宣布有效。

## 4. AI IDE 统一提示词

将以下提示词与本目录一并交给任一 AI IDE：

```text
你正在开发 AI Hot Radar。先完整阅读 README.md、docs/00-master-spec.md，
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

# 11｜代码走读：从用户动作走到迁移和测试

## 1. 走读原则

不要从目录树逐个念文件。先选一个业务动作，按“入口 → 编排 → 持久化 → 出口 → 测试”走完，
并在每一步回答：输入是什么、谁拥有状态、哪里提交、失败如何处理、如何证明。

## 2. 路线 A：一条资讯如何进入首页

1. `config/sources.yaml` 找一个 source，`ingestion-profiles.yaml` 看其 adapter 契约；
2. `ingestion/scheduler.py::_claim_due_sources`：解释 due query 和 `SKIP LOCKED`；
3. `ingestion/pipeline.py`：discover、回源、全文门禁；
4. `ingestion/repository.py`：raw/item/revision/chunk 的幂等写；
5. `processing/worker.py`：advisory lock 和阶段推进；
6. `processing/selection.py`：评分、来源/类别配额；
7. `ContentController.java`：公开 DTO 和 SQL；
8. `apps/web/app/page.tsx` 及组件：SSR、筛选和卡片；
9. 对应 fixture、scheduler、selection、controller 和 Web 测试。

追问准备：如果 cursor 先提交会怎样？为什么单源失败不 rollback 全批？为什么 12:00 不是精确
发布时间？为什么精选不是按热度直接取前 12？

## 3. 路线 B：订阅者如何收到日报

1. 报告生成：`processing/report.py` 和 CLI `report`；
2. Flyway 中 report 状态和 subscription/delivery 表；
3. `ReportAdminController` + `ReportPublicationService`：受控发布；
4. `ReportSubscriptionController/Service`：申请、token、确认、退订；
5. `ReportEmailDeliveryService`：due query、唯一键、锁、重试；
6. `SubscriptionMailer`：HTML/纯文本和退订链接；
7. Web 报告页和 subscription modal；
8. Java subscription/email tests 与生产 SMTP dry-run 证据。

追问准备：为什么不直接发生成结果？如何避免重复？SMTP 已收但本地更新失败怎么办？为什么不用
队列？退订与正在发送之间的竞态怎么处理？

## 4. 路线 C：一个 RAG 问题

1. Web `/ask` 提交和 SSE；
2. `rag/api.py`：输入、限流、生命周期；
3. `conversation.py`/`planner.py`/`temporal.py`：多轮和计划；
4. `cache.py`：语料指纹；
5. `retrieval.py`：dense/sparse/temporal SQL；
6. `fusion.py`/`dimensions.py`/`rerank.py`：融合和排序；
7. `folding.py`/`parent.py`/`context.py`：事件去重与上下文；
8. `answer.py`/`support.py`/`incremental.py`：生成、绑定、出口；
9. `rag_query`/`rag_citation` 迁移和 persistence；
10. 单元测试、90 题评测和 `/eval` 证据。

追问准备：正确证据在哪个通道？RRF 为什么不用分数相加？模型编造 URL 会怎样？为什么 parent
不作为 citation？缓存如何避免过期新闻？如何区分检索错和解析错？

## 5. 路线 D：运营者切换生成模型

1. ADR-0027 解释需求和边界；
2. Flyway 模型目录、当前配置、价目版本；
3. `GenerationModelController` 的 VIEWER/OPERATOR、目标确认和幂等；
4. Python model config repository 每次创建客户端读取；
5. `llm_usage` 保存 model/config/price snapshot；
6. Web 模型页只展示 allowlist，不允许任意字符串；
7. 测试切换只影响之后请求，不改 embedding/历史内容。

## 6. 走读时的证据层级

代码说明“怎么做”，Flyway 说明“真实有什么表”，测试说明“哪些性质被守住”，ADR 说明“为什么
这样选”，status/eval 说明“在什么环境实际验证”。五层要能相互指向，不能只展示一段漂亮代码。

## 7. 十个必会函数/查询

1. source due claim；2. source failure reschedule；3. canonical/idempotent upsert；4. fulltext gate；
5. processing advisory lock；6. RRF fusion；7. evidence number binding；8. answer support cleanup；
9. report state transition；10. delivery candidate claim。

每个函数至少能讲一个失败测试和一个设计替代方案。


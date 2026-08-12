# 04｜后端边界、数据库与一致性
## Java 与 Python 为什么分开

| Core API（Java） | AI Service（Python） |
|---|---|
| 内容、Story、报告公共读 API | Feed/API/HTML/GitHub/arXiv 适配 |
| 报告发布、订阅、投递事实 | 正文抽取、清洗、切块、向量 |
| VIEWER/OPERATOR、二次确认、审计 | LLM 结构化、聚类、评分、报告生成 |
| Flyway 启动迁移与稳定 DTO | Query Planner、检索、重排、生成、评测 |

Java 边界偏事务、权限和稳定 API；Python 边界偏模型与数据处理生态。跨服务使用 OpenAPI/Schema
生成契约，不共享源代码对象。拆分减少模型迭代对用户和订阅事实的影响，但也增加 header、超时、
错误语义和版本兼容等“接缝”测试责任。

## PostgreSQL 为什么是唯一事实源

内容状态、正文版本、Story 关系、发布报告、订阅、投递、管理审计、向量、检索轨迹需要事务、
过滤和一致回滚。放在同一 PostgreSQL 中可以在一次查询里约束 `PUBLISHED`、时间、实体、来源和
向量，不产生业务库与向量库的异步双写真空期。

pgvector 不是因为“永远最强”，而是当前八千级分块、低并发和强 SQL 过滤下最小复杂度的选择。
当单库容量、并发、构建时间或召回延迟经压测越界时，才以双写/回填/切换 ADR 迁移。

## Redis 为什么不能成为业务事实

Redis 用于：公共读缓存、限流滑窗、RAG 结果/Embedding/重排缓存、短租约和短状态。缓存键含版本
与新鲜度；发布/撤选或新语料到达时失效。即使 Redis 全丢，内容、报告、订阅和投递仍必须正确，
只是短期变慢。这是判断“数据能否放 Redis”的最简单测试。

## Flyway 与契约演进

数据库只能通过 `database/migrations/` 的 Flyway V001–V024 演进；禁止手改生产表。CI 同时测
空库创建和上一发布版本升级。迁移必须与旧应用尽量向前兼容：先加可空字段/新表和双读，再切应用，
最后另一个版本清理；生产发布失败优先回应用镜像，不把不可逆 DDL 当作普通回滚。

Java DTO、Python Pydantic 和 OpenAPI/JSON Schema 的共享部分由契约生成并做 diff 门禁。任何公开
API 破坏性变化先写 ADR；错误使用 Problem JSON/稳定错误码，不让浏览器解析内部异常文本。

## 四类幂等

1. **采集幂等**：`source_id + external_id`、canonical URL、内容 hash 与 upsert；
2. **处理幂等**：revision/input hash + processor/prompt/model version，晚到结果 CAS 失败；
3. **报告幂等**：周期 key/version 与 PUBLISHED 状态，重复批处理不新增同一期事实；
4. **投递幂等**：`(subscription_id, report_id)` 唯一键、`FOR UPDATE SKIP LOCKED` 与 delivery key。

幂等不是“捕获唯一键异常就算完”，还需要保存输入版本、输出版本、尝试和最终状态，使重复请求
能返回同一个结果或安全重入。

## 状态、锁与事务

- Scheduler 使用有期限 source 租约，进程退出后可重领；
- Pipeline 使用数据库 advisory lock，避免两个副本同时批处理；
- 状态推进比较当前状态和 input version，过期结果记录但不覆盖；
- 人工锁定 Story 后，自动聚类只能提建议；
- 报告只在引用和确定性门通过后转 PUBLISHED；
- 邮件领取用行锁并跳过已锁记录，发送结果写回独立 delivery 状态。

## `outbox_event` 的真实状态

规格预留了数据库 Outbox，但当前表**只写不读**，`published_at` 没有工作的消费者。一致性与异步
任务由 PostgreSQL 轮询、租约和幂等保证。面试时应主动说清；若出现需要独立扩缩容、稳定重放和
持续 backlog 的消费者，再写 ADR 引入 publisher/queue，而不是把预留结构包装成已完成能力。

## 缓存一致性

公共列表采用短 TTL 与发布后失效；RAG 缓存键包含问题、计划、模型/Prompt/索引版本和 corpus
freshness。缓存击穿用互斥重建或 stale-while-revalidate；管理敏感响应不缓存。客户端不维护
第二份筛选真相，URL search params 是唯一筛选状态。

## 故障与降级

- Redis 不可用：回数据库，限流 fail-closed/受控降级，不改变业务事实；
- LLM 不可用：保留待加工状态，已有内容与报告继续读取；
- 单源失败：更新该 source 健康与重试，不停全局；
- SMTP 失败：有限重试和审计，不回滚 PUBLISHED；
- Worker 重启：租约过期重领、幂等重放；
- 数据库恢复：停调度、恢复验证备份、运行 Flyway，再从 checkpoint/任务表续跑。

## 最容易被追问的接缝

匿名限流曾出现 Next 未正确传递客户端 IP，两个服务单测都绿但生产共用一个桶。修复重点不是
“加一行 header”，而是定义可信代理链、只接受 Caddy/内部代理的 forwarded headers，并在服务
接缝写端到端测试。跨语言系统最大的风险经常不在单个模块，而在两个模块都以为对方处理了某件事。

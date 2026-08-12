# AI Hot Radar 面试准备总入口

本目录不是第二套规格；事实和边界仍以 [`../spec/00-master-spec.md`](../spec/00-master-spec.md)、
领域规格、ADR 和状态证据为准。先读完整的 [`../handbook/`](../handbook/README.md) 建立知识，
再用这里训练不同面试场景。这里不是摘要，而是“怎么讲、从哪里看代码、被追问如何证明”。

## 推荐阅读顺序

| 顺序 | 文档 | 先回答的问题 |
|---:|---|---|
| 00 | [`00-project-one-pager.md`](00-project-one-pager.md) | 如何用 30 秒、2 分钟、5 分钟介绍项目？ |
| 01 | [`01-business-and-architecture.md`](01-business-and-architecture.md) | 业务闭环与三个服务为什么这样拆？ |
| 02 | [`02-ingestion-and-data-model.md`](02-ingestion-and-data-model.md) | 一条公开信息怎样变成可信、可引用的数据？ |
| 03 | [`03-rag-deep-dive.md`](03-rag-deep-dive.md) | Dense、Sparse、时间、重排、引用和评测怎样协作？ |
| 04 | [`04-backend-and-consistency.md`](04-backend-and-consistency.md) | PostgreSQL/Redis/Flyway/幂等怎样保证一致性？ |
| 05 | [`05-frontend-product.md`](05-frontend-product.md) | Next.js 页面如何承载内容、RAG 与工程解释？ |
| 06 | [`06-deployment-security-ops.md`](06-deployment-security-ops.md) | 2C4G 如何部署、加固、备份、告警和迁移？ |
| 07 | [`07-interview-question-bank.md`](07-interview-question-bank.md) | 面试官会追问哪些取舍与反例？ |
| 08 | [`08-resume-and-star-stories.md`](08-resume-and-star-stories.md) | 简历怎么写，真实 STAR 故事怎么讲？ |
| 09 | [`09-system-design-whiteboard.md`](09-system-design-whiteboard.md) | 5/15/30 分钟白板如何展开和扩容？ |
| 10 | [`10-demo-script.md`](10-demo-script.md) | 现场演示如何在网络正常或异常时完成？ |
| 11 | [`11-code-walkthrough.md`](11-code-walkthrough.md) | 面试官点开仓库后怎样沿四条链路讲代码？ |
| 12 | [`12-fourteen-day-study-plan.md`](12-fourteen-day-study-plan.md) | 如何在 14 天内从会用变成能解释和推导？ |

补充材料：[`../interview-guide.md`](../interview-guide.md) 是已冻结的早期深挖稿，内容已迁入
工程手册和本目录；[`../status/project-status.md`](../status/project-status.md) 是累计历史，不用于
判断当前生产事实。

## 四阶段训练法

1. **理解**：不看答案画业务图、运行图、ER 图和 RAG 图；
2. **定位**：任意说一个步骤，30 秒内找到代码、迁移、测试和 ADR；
3. **表达**：同一项目练 30 秒、3 分钟、10 分钟和白板版本；
4. **压力测试**：让对方质疑数字、扩容、失败、没用 Kafka/K8s、Outbox 未消费等边界。

## 三条讲解纪律

1. **动态数据与固定评测分开。** 首页、`/ops`、信源后台读当前数据库；`/eval` 是固定语料、
   模型和黄金集上的发布快照，只在主动重评时变化。
2. **实现事实与技术判断分开。** “使用 pgvector HNSW”是事实；“当前不需要 Milvus”是基于
   八千级分块、低并发和事务过滤的阶段性判断。
3. **预留不等于完成。** `outbox_event` 当前只写不读；不能把它包装成已经工作的消息架构。

## 证据索引

| 主张 | 展示证据 |
|---|---|
| 产品可用 | 线上站点、根 README 五张脱敏截图 |
| 内容持续更新 | `/`、`/ops`、`/admin/sources` 的本次读取和最近成功时间 |
| RAG 达到发布门 | `/eval`、`../status/eval/`、90 题逐题 artifacts |
| 引用可追溯 | `/ask/{id}` 的句级编号、原文卡片和检索轨迹 |
| 报告与邮件闭环 | `/reports`、订阅确认、`email_delivery` 状态与 SMTP 验收 |
| 生产可恢复 | `../status/production/`、备份清单、SHA-256 和隔离恢复记录 |
| 技术取舍有依据 | `../adr/`、B2/B8/B13/GEN-FIX 负结果与回滚条件 |

面试前只更新动态数字，不改历史实验结果；任何数字都要说明日期、样本量和测量环境。

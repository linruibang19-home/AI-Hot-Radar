# 09｜系统设计白板讲解
## 5 分钟版本

1. 写需求：多源 AI 资讯 → 事件/报告 → 可引用 RAG；强调时效、去重、引用和低成本单机。
2. 画主链：Sources → Ingestion/AI → PostgreSQL → Core API → Next.js；Redis 在旁边标“cache only”。
3. 画 RAG：Dense + Sparse + Temporal → RRF → Reranker → Evidence → Generate → Validate。
4. 写三个约束：PostgreSQL 事实源、RSS 不是全文、模型输出不可信。
5. 写生产：Caddy + Compose + SHA image + backup/restore。

## 15 分钟版本

### 1. 澄清需求

- 用户是匿名读者还是企业知识库？当前是公开情报，不做账号/租户/ACL。
- 时效要求是什么？P0 入站 p95 20 分钟，RAG 完整回答 p95 20 秒目标。
- 数据规模和并发？当前约 140 个信源、3k 内容、1.5w chunks、低并发作品集（数量级即可，
  精确值见 [`00-project-one-pager.md`](00-project-one-pager.md) 的带日期快照）。
- 输出有哪些？网站、日周月报告、邮件、RAG、工程质量页。

### 2. 核心实体

画 `source → content_item → revision → chunk`，旁边连 `entity/topic`；多个 item 连 `story`；
Story 连 `report`；query 连 retrieval trace/citation。强调 chunk 引用原文、Story/Report/RAG 是生成层。

### 3. 写入链

Scheduler lease → adapter discover → canonical fetch → fulltext gate → idempotent revision → schema enrichment
→ chunk/embed → dedup/story → publish。每段写 timeout/retry/idempotency/trace。

### 4. 读取链

Next SSR → Core API → PostgreSQL/Redis；RAG 由 Web 同源代理 AI Service。Caddy 只有公网入口。

### 5. 一致性和失败

PostgreSQL 事务、revision CAS、advisory lock、subscription/report unique delivery、Redis 可丢。
单源/模型/SMTP/Worker 故障分别隔离，网站继续读旧的 PUBLISHED 数据。

### 6. 质量与安全

固定黄金集、引用绑定、逐句支持、拒答；SSRF、RBAC、二次确认、secret env、内部端口隔离、备份恢复。

## 30 分钟版本

在 15 分钟基础上深入四个议题：

### A. RAG 为什么不只是向量搜索

解释时间解析、实体过滤、dense/sparse 切片、RRF 跨量纲、cross-encoder、Story 折叠、父块和服务器引用。
用 dense 14 / sparse 1 / fusion 3 与 B2/B8 负结果证明每层作用。

### B. 数据模型为什么同库

一次检索需要状态、时间、实体、来源、Story 和向量联合过滤；PostgreSQL 让状态推进、删除/下架、
发布和引用处于同一事务边界。指出迁独立向量库时必须解决双写、回填、版本切换和权限前置过滤。

### C. 报告/邮件怎样 exactly-once-ish

不承诺网络世界绝对 exactly once；数据库唯一事实和领取锁提供业务幂等，SMTP 响应与网络断开之间仍
可能不确定。可使用 provider message id/幂等 API 改善，当前至少保证系统重扫不主动创建重复 delivery。

### D. 生产怎样可恢复

SHA 镜像、向前兼容迁移、preflight、health/smoke、上一 SHA、每日 dump/SHA、异机副本、隔离恢复与
DNS 双机切换。说明备份恢复才是证据，不是“有 backup 容器”。

## 容量估算说法

当前 1.5w 量级 chunks 很小，向量 1024 维 float 约 4KB/条，纯向量仅几十 MB，索引、文本与 PostgreSQL
开销更大但仍在单机范围。真正增长项是正文、revision、索引、备份、镜像和日志。不能只用向量裸大小
推磁盘；以实际表/index/volume 和增长率监控。

## 100 倍扩展路线

```text
先测：API RED / DB query & pool / cache hit / external model P95 / worker backlog / disk
→ 内容读缓存与静态化
→ SQL/index/connection pool、分区与归档
→ Pipeline 横向 Worker + 真正的 outbox publisher/queue
→ 按证据拆搜索/向量读路径或只读副本
→ 多节点与编排（到此才评估 Kubernetes）
```

私有语料进入后必须先加用户、租户、ACL，并在召回前做权限过滤；不能先召回再只在前端隐藏。

## 白板常见陷阱

- 一上来画 Kafka/K8s/微服务，却没说吞吐、团队和故障域；
- 用向量数据库代替数据模型，忽略时间、状态和权限过滤；
- 只讲 happy path，不讲重复任务、晚到结果、删除和恢复；
- 把模型生成摘要当引用证据；
- 说 exactly once 却没解释 SMTP/API 的不确定窗口；
- 用单个离线分数代表线上成熟度，不讲 run、样本和反馈。

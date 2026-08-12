# 实现事实校准与文档教材重构（2026-08-13）

任务卡：`TASK-M5-014`。本任务只改变文档、ADR 和文档门禁，不改变业务代码、数据库、API、
RAG 策略、生产镜像或生产数据。

## 审计发现与处理

| 优先级 | 发现 | 代码事实 | 处理 |
|---|---|---|---|
| P0 | 架构图声称 Outbox Publisher/Consumer | outbox 只写/清理，无 reader；任务靠 DB 轮询 | ADR-0028，修 spec02/10/11 |
| P0 | 运行手册称 Java Scheduler 采集 | Compose scheduler/pipeline 都运行 Python CLI | 修服务边界和端到端步骤 |
| P0 | 规格把 evidence passage/embedding 写成独立表 | Flyway 使用 `content_chunk` 同行存向量 | ADR-0029，修 spec00/03/04 |
| P0 | 部署规格写 Nginx 和独立浏览器 worker | 生产入口是 Caddy，浏览器 adapter 默认关闭 | 修 spec02 当前拓扑 |
| P1 | README/交付索引测试数停在 878 | TASK-M5-013/PR #14 为 884 passed/2 skipped | 更新当前入口，历史快照保留 |
| P1 | 仓库卫生文档记录前序 CI run | 最终全绿 run 为 31610709745 | 日期快照中补充最终判定 |
| P2 | 12 份面试稿过度压缩 | 缺完整业务顺序、失败、代码和技术边界 | 新建 15 章 handbook，扩题库/STAR/走读 |
| P2 | status 历史与当前混读 | 86 份状态文档含快照和实验 | 增加冻结提示、归档政策和自动校验 |

## 新知识结构

- `docs/handbook/`：15 章，从产品到三端、RAG、部署和演进；
- `docs/interview/`：30 秒至 30 分钟表达、120 题、10 个 STAR、白板、演示、代码走读、14 天计划；
- `docs/archive-policy.md`：CURRENT/SPEC/DESIGN/EVIDENCE/LEGACY 分级；
- `scripts/validate_docs.py`：链接和已知漂移自动门禁。

## 不做的事

- 不为配合文档重构 Outbox、队列或数据库表；
- 不改写历史评测和负结果；
- 不把动态生产计数更新成无日期常量；
- 不因面试包装加入 Kafka、Elasticsearch、Kubernetes 或 GraphRAG；
- 不触发生产部署。

## 验收

本地门禁：

- `python scripts/validate_spec.py`：规格、140 信源和 schema 一致性；
- `python scripts/validate_docs.py`：手册/面试教材完整性、本地链接和关键实现事实；
- `git diff --check`：补丁空白与冲突标记；
- Python 全量测试：避免文档任务掩盖工作区漂移。

GitHub PR 与 CI run 由任务交付记录保存，不把可变化的 PR 状态写成永久“当前事实”。

# 03｜运行时与服务架构

## 1. 当前部署不是“微服务集群”

这是一个单机 Docker Compose 上的模块化系统，有清晰跨语言边界，但没有 Kubernetes、Kafka、
服务网格或独立搜索集群。这样做与当前 2C4G 容量和个人运维能力匹配。

## 2. 生产拓扑

| 进程/容器 | 技术 | 职责 | 依赖 |
|---|---|---|---|
| `caddy` | Caddy 2 | 80/443、TLS、反向代理 | web/core/AI |
| `web` | Next.js 15 / React 19 | SSR、页面、同源代理、交互 | Core API、AI Service |
| `core-api` | Java 21 / Spring Boot 3 | 公开读、报告、订阅、邮件、管理审计 | PostgreSQL、Redis、SMTP |
| `ai-service` | Python 3.12 / FastAPI | RAG HTTP、健康检查 | PostgreSQL、Redis、模型 API |
| `scheduler` | 同一 Python 镜像 | 到期信源领取和采集 | PostgreSQL、公开站点 |
| `pipeline` | 同一 Python 镜像 | 内容处理、选择、报告、索引 | PostgreSQL、模型 API |
| `postgres` | PostgreSQL + pgvector | 唯一业务事实源 | 数据卷 |
| `redis` | Redis | 缓存、限流、短会话、短锁 | 数据卷/内存 |
| 备份/监控 | 脚本与 sidecar | 快照、健康与告警 | 数据库、宿主机 |

同一 Python 镜像运行三种角色并不代表三份服务代码。它通过不同启动命令隔离 HTTP、采集循环
和处理循环，减少镜像漂移，同时保留独立重启和资源边界。

## 3. 为什么 Java 与 Python 分开

### Java Core API 适合持有的边界

- 稳定 HTTP 契约和 DTO；
- 报告发布状态机；
- 订阅确认、token、投递幂等；
- 管理鉴权、目标确认、审计；
- JDBC 事务和显式 SQL 查询。

### Python AI Service 适合持有的边界

- 多种 Feed/API/HTML/PDF 采集；
- 文本抽取、分块和 Pydantic Schema；
- embedding、rerank、LLM；
- RAG 实验、黄金集和离线评测；
- 数据处理批任务。

边界不是“Java 做业务、Python 做 AI”这么粗。采集调度和内容流水线也在 Python；Java
拥有邮件调度，但不拥有采集调度。ADR-0028 专门避免把两者混称为 Scheduler。

## 4. 服务通信

- Web 到 Core/AI：HTTP，同一 Caddy 域名下代理；浏览器不看内部地址；
- Core/AI/Pipeline/Scheduler 到 PostgreSQL：各自连接池或短连接；
- Core/AI 到 Redis：缓存/限流可降级；
- Pipeline/AI 到模型供应商：带超时、有限重试、用量记录；
- Core 到 SMTP：确认信和报告邮件；失败落 delivery 状态。

当前后台处理主要通过共享 PostgreSQL 状态协调，不通过消息 Broker。共享库降低单机运维成本，
代价是要严格定义表所有权、锁和查询负载。

## 5. PostgreSQL 与 Redis 的边界

PostgreSQL 保存任何“丢失后用户会发现业务不一致”的状态：内容、报告、订阅、投递、模型配置、
RAG 查询与引用。Redis 保存可从 PostgreSQL 或输入重新构造的状态：答案缓存、限流窗口、短会话。

判断题：如果 Redis 清空后订阅消失，设计就是错的；如果答案缓存消失导致下一次多调用模型，
但结果仍可生成，则边界是合理的。

## 6. Outbox 的真实状态

Flyway 有 `outbox_event` 和 `processed_event`，采集会写 outbox，保留任务会清理旧行；当前没有
Publisher/Consumer。系统一致性依赖 PostgreSQL 状态轮询、锁、版本与唯一键。未来启用 Broker
需要新的消费者代码、积压指标、死信和重放验收，不是“改一行 Compose”。

## 7. 扩容顺序

当前证据支持的顺序：

1. 先优化慢 SQL、连接池、缓存与批大小；
2. 独立增加 Python worker 副本，验证锁和幂等；
3. 如果数据库轮询成为瓶颈，再评估消息 Broker；
4. 如果全文/向量规模让 PostgreSQL 不能满足 SLO，再评估 OpenSearch/专用向量库；
5. 只有多机编排、滚动发布和资源隔离成本真正超过 Compose 时才评估 Kubernetes。

## 8. 代码入口

- 生产拓扑：`infra/compose/docker-compose.prod.yml`
- Caddy：`infra/caddy/Caddyfile`
- Python CLI 角色：`apps/ai-service/src/ahr/cli.py`
- 采集调度：`apps/ai-service/src/ahr/ingestion/scheduler.py`
- 处理 worker：`apps/ai-service/src/ahr/processing/worker.py`
- Java 入口：`apps/core-api/src/main/java/com/aihotradar/coreapi/CoreApiApplication.java`


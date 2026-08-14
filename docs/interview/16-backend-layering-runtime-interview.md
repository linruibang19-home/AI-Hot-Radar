# 16｜后端分层、JVM 与 Redis 面试深挖

## 30 秒回答

项目不是传统全局四层目录，而是按 `content/subscription/admin` 业务域组织，域内使用
Controller、Service、Repository 分层。Java 负责稳定 HTTP、发布/订阅/投递、RBAC/审计和事务；
Python 3.12 确实使用 FastAPI，但同一包还运行 Scheduler 与 Pipeline，按 ingestion、processing、
rag 分域。PostgreSQL 是唯一事实源，Redis 只做短 TTL 读缓存、RAG 缓存和匿名限流。生产为香港
2C4G Compose；Core API 512 MiB 上限，Java 21 最大堆实测估算约 371 MiB。

## Q1：为什么没有 `controller/service/dao/entity` 四个顶层目录？

**答：** 我采用 package-by-feature，而不是 package-by-layer。四个全局目录在 CRUD 示例里简单，
但一个 Story 功能会散落四处；按业务域组织让修改、测试和所有权聚合。域内仍有 HTTP、业务编排、
持久化三层，例如 `StoryController → StoryService → StoryRepository`。我还用 ArchUnit 禁止任何
`@RestController` 直接依赖 Spring JDBC，所以不是口头分层。

**追问：为什么 ContentController 还能直接委托 Repository？**

纯只读 projection 没有状态迁移时允许薄 Controller 直接委托 Repository，避免只做转发的空 Service；
一旦出现周期规范化、阈值、聚合、事务或状态机，就进入 Service。硬规则是 Controller 不写 SQL、
不依赖 JDBC，业务规则不能藏在 HTTP 层。

## Q2：DAO 和 Repository 有什么区别？

**答：** 在这个项目里 Repository 承担 DAO 的数据库访问职责，但接口围绕业务读模型/聚合命名，
不是按表机械生成 CRUD。比如 ReportRepository 一次面对报告主记录、条目和前后导航，Service 再
组成页面需要的章节与统计。命名差异不重要，关键是参数化 SQL、事务归属和测试边界。

## Q3：为什么没有 JPA Entity，是不是架构不完整？

**答：** 不是。表由 Flyway V001–V026 定义，Java 用 Spring JDBC 和 immutable record 读模型。
系统大量使用窗口、CTE、JSON、`SKIP LOCKED`、pgvector 与定制 projection；JPA 会增加映射和
N+1 风险，却没有带来聚合根行为。普通 CRUD 增长时可以局部使用 Spring Data JDBC/JPA，不需要
为了目录观感整体迁移。

## Q4：Java Core API 具体做什么，为什么不全用 FastAPI？

**答：** Java 承担变化较慢且强调一致性的边界：公共内容 API、报告发布状态机、双确认订阅、定时
邮件、VIEWER/OPERATOR、二次确认、幂等与审计。Python 强在抓取、文本处理、模型 SDK、向量与
评测。全用 FastAPI 技术上可行，但会把运营权限和投递事实与频繁变化的 AI pipeline 绑定发布；
拆分后代价是必须认真做契约、错误语义、请求 ID 与时间语义测试。

## Q5：Python 是 FastAPI 项目吗，怎么分层？

**答：** HTTP 角色是 FastAPI，但项目不等于一个 Web CRUD。一个镜像运行三种进程：uvicorn
RAG API、source scheduler、processing pipeline。代码按 ingestion/processing/rag 分域；每域内有
transport、orchestration、policy、infrastructure。AST 测试限制 FastAPI 只能出现在组合根、健康
检查和 `rag/api.py`，也限制 ingestion/rag 的反向依赖。

## Q6：为什么不用 LangChain/LangGraph？

**答：** 当前 RAG 是固定、有状态留痕但非开放工具自治的编排：planner、四路召回、RRF、rerank、
父块、生成、引用绑定和支持度门都有明确接口、指标与失败点。直接 Python 编排更容易保存每阶段
trace、控制降级和写细粒度测试。只有出现动态工具选择、长流程 checkpoint/人工中断或多个 Agent
协作的真实需求，才评估 LangGraph；现在引入只会增加抽象层，不提高召回或引用正确性。

## Q7：Java 与 Python 怎么保证一致性？

**答：** 两者不共享内存对象，PostgreSQL 是事实源；OpenAPI/JSON Schema/Pydantic/生成 DTO 做
契约。后台用租约、advisory lock、状态/version 和幂等键轮询推进。`outbox_event` 当前只写不读，
我会主动说明尚未形成消息总线，避免把设计预留包装成已实现能力。

## Q8：生产 JVM 给了多少内存？

**答：** 2026-08-14 当前香港机是 Ubuntu 22.04.5、2C4G（系统可见约 3.4 GiB）。Core API 容器
`mem_limit=512m`，Java 21 命令带 `-XX:MaxRAMPercentage=75`，同环境估算最大 heap 371.25 MiB。
不是“JVM 512M”：容器还要容纳 metaspace、thread stack、code cache、direct/native memory。

## Q9：为什么不用 `-Xmx` 固定值？

**答：** 百分比随容器上限调整，能复用同一镜像；真正的保护是 Compose `mem_limit`。没有上限时
百分比会按宿主机放大，所以生产 Compose 强制上限。若平台固定且希望更确定，也可以用 `-Xms/-Xmx`
并结合 Native Memory Tracking 和压测校准，不应只看 heap。

## Q10：Redis 用在哪些地方？

**答：** Java 用 Spring Cache 缓存精选/主题/统计等公共读模型，TTL 2–10 分钟；Python 缓存 query
embedding、带 corpus fingerprint 的答案、0.97 阈值的近似问法、多轮 transcript 和 30 秒 ops
聚合；另有匿名 RAG 分钟/日限流。Redis 128 MiB `allkeys-lru`，容器 192 MiB，无持久化。

## Q11：Redis 挂了会怎样？

**答：** 内容、报告、订阅、投递和历史回答都在 PostgreSQL，所以不丢业务事实。公共读取回源
数据库，RAG 重新调用供应商，延迟和成本上升；限流当前 fail-open，因为它防费用滥用而不是认证
安全。若 Redis 故障造成 DB 打满，可对非核心统计受控降级，但不能返回伪造数据。

## Q12：怎样解决缓存一致性？

**答：** 公共读用短 TTL；RAG 精确答案键包含规范化问题、Prompt/pipeline version 和 corpus
fingerprint。新鲜问题绑定精确语料状态，原理/对比类绑定按日状态，拒答不缓存。Redis 清空只产生
miss。管理敏感响应不缓存，数据库仍是最终判断。

## Q13：缓存踩过什么真实坑？

**答：** Java record 隐式 final，原 `NON_FINAL` 多态序列化没有写类型头，第一次 miss 正常，第二次
命中反序列化 500。修复为受限白名单的 `EVERYTHING` 类型信息，并增加序列化往返与 key collision
测试。这说明缓存必须测 cold 和 warm 两条路径。

## Q14：邮件发送和数据库事务如何保证一致？

**答：** 不假装 SMTP 可以参与本地事务。系统先生成唯一 `email_delivery(subscription_id,
report_id)`，`SKIP LOCKED` 领取并标为 SENDING，再调用 SMTP，随后写 SENT/RETRYABLE_FAILED/
PERMANENT_FAILED。最多三次并可回收 15 分钟 stale claim。供应商已收但本地确认丢失仍是经典
不确定窗口，需要供应商幂等 id 才能彻底消除；当前通过唯一投递与有限重试降低风险。

## Q15：为什么 2C4G 可以运行，哪里最危险？

**答：** 模型推理在 DeepSeek/SiliconFlow，不占本地 GPU；主要是 HTTP、文本处理、PostgreSQL、
JVM/Python。所有容器有上限和有界日志，Redis 有独立 maxmemory，swap 2 GiB。当前低风险生产验证
不是容量寻顶；瞬时观察 Scheduler 约 269/320 MiB，比 Core API 更接近上限，应该优先监控批次
峰值、OOMKill、DB pool、磁盘和外部 API P95。

## Q16：腾讯云 Ubuntu 24.04 备案期间怎么处理？

**答：** 当前香港站继续提供服务，广州机只是迁移目标。备案完成后在新机部署同 SHA 镜像、恢复
校验备份、用临时入口 smoke，再切 DNS 并保留旧机 48–72 小时。域名和网站名不依赖主机，因此
无需改产品名；Ubuntu 24.04 对容器化应用没有业务层迁移成本，但仍需核对 Docker、防火墙、时钟、
swap、日志和备份。

## 代码证据清单

- Java 分层：`apps/core-api/src/main/java/com/aihotradar/coreapi/content/`
- 架构门禁：`apps/core-api/src/test/java/com/aihotradar/coreapi/CoreApiArchitectureTest.java`
- Python 分域：`apps/ai-service/src/ahr/`
- Python 门禁：`apps/ai-service/tests/test_architecture_layers.py`
- Redis：`cache/CacheConfig.java`、`rag/cache.py`、`rag/ratelimit.py`
- JVM/限额：`apps/core-api/Dockerfile`、`infra/compose/docker-compose.prod.yml`
- 部署：`.github/workflows/release.yml`、`infra/scripts/deploy-production.sh`

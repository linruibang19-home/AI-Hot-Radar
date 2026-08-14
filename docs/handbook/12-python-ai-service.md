# 12｜Python AI Service 与后台流水线

## 1. 一个代码库，三种运行角色

Python 3.12 包通过 `ahr.cli` 和 FastAPI 运行：

- `ai-service`：RAG/健康 HTTP；
- `scheduler`：循环领取 source 并采集；
- `pipeline`：循环领取内容处理工作。

角色拆进程而不拆仓库，既隔离故障和生命周期，又复用模型、repository、配置和测试。

## 2. 工程分层

| 目录 | 内容 |
|---|---|
| `ingestion` | source 配置、adapter、HTTP、抽取、门禁、repository、scheduler |
| `processing` | 分块、结构化、聚类、热度、选择、报告、邮件工具、worker |
| `rag` | 计划、检索、融合、重排、生成、引用、缓存、评测 |
| 根模块 | FastAPI app、配置、健康、CLI、provider usage |

领域包内部继续区分 transport、application orchestration、domain policy 和 infrastructure。
FastAPI 只允许在 `main.py`、`health.py`、`rag/api.py`；`tests/test_architecture_layers.py` 用 AST
扫描约束 Web 框架不进入领域规则，同时禁止 ingestion 反向依赖 processing/rag、rag 依赖
ingestion。Python 不需要复制 Java 的目录名，关键是依赖方向相同且可测试。

## 3. 配置

Pydantic Settings 读取环境变量，关键 provider 和数据库配置缺失时 fail fast。生产生成模型名来自
PostgreSQL 目录，`.env` 中模型仅支持离线/测试兼容。密钥永不进入数据库、页面或 git。

## 4. 采集并发与错误

HTTP 客户端统一超时、重试、User-Agent、SSRF/host 限制。Scheduler 顺序/有界处理领取的源，
单源异常 rollback 后继续其他源。failure count 决定退避；jitter 避免所有源同一秒唤醒。

## 5. Processing Worker

Worker 用 advisory lock 保证单机/多副本不会同时执行不安全的全局阶段，再按处理状态选择工作。
每阶段只提交完整结果；异常 rollback，旧版本输出不能覆盖新 revision。当前不是 outbox consumer。

## 6. Provider 封装

Embedding、reranker 和 LLM 都验证响应数量、顺序、维度或 schema，并记录 usage/latency。429/5xx
有限重试，配置错误、维度错误和不兼容模型直接失败，不用部分结果“凑合入库”。

## 7. RAG HTTP

FastAPI 路由在昂贵调用前执行输入边界和 rate limit。Service 编排缓存、计划、召回、重排、生成、
支持检查和持久化。SSE/流式路径必须与非流式最终答案一致；后台任务关闭和客户端断开要清理。

## 8. CLI 是可重复运维接口

`sync-sources`、`probe`、`ingest`、`schedule`、`pipeline`、`embed`、`rag-eval`、`select`、`report`
等命令共享代码路径，便于一次性回填和常驻循环一致。生产操作必须通过 Compose exec 并记录命令，
不能在宿主机随意运行另一个 Python 环境。

## 9. 测试设计

- fixture 重放第三方响应，不在 CI 高频请求真实站点；
- HTTP transport mock 验证重试、顺序、维度和错误；
- SQL repository 集成测试验证 PostgreSQL 行为；
- RAG 单测按 planner/retrieval/fusion/rerank/cache/answer/incremental 拆开；
- 黄金集验证端到端指标；
- production Compose 静态测试确保秘密必填、只有 Caddy 暴露、日志有界。

## 10. 典型排障

如果答案错，先查看 query trace 判断候选是否正确。候选错查 planner/retrieval；候选对但排序错查
fusion/rerank；证据对但回答错查 prompt/模型；正文对却拒答查 parser/support gate。这套分层比
直接换大模型更快定位。

生产进程、跨语言边界和缓存细节见
[`19-backend-layering-runtime-and-redis.md`](19-backend-layering-runtime-and-redis.md)。

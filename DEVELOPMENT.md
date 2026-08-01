# 本地开发指南

> 对应任务卡：`TASK-M0-001`｜里程碑：M0 工程骨架

## 1. 前置条件

| 工具 | 版本 | 用途 |
|---|---|---|
| Docker Desktop | 最新稳定版 | 运行整套本地栈 |
| JDK | 21 | core-api 本地构建（不用 Docker 时） |
| Node.js | 22 LTS | web 本地开发 |
| Python | 3.12 | ai-service 本地开发、规格校验 |

只用 Docker 时，仅需 Docker Desktop。

## 2. 一条命令启动

```bash
cp .env.example .env
```

```bash
docker compose -f infra/compose/docker-compose.yml up -d --build
```

首次构建需要拉取 Gradle/Node 镜像并编译，约 5–10 分钟。

## 3. 验证三个服务

```bash
curl -s http://localhost:8080/health/ready && curl -s http://localhost:8000/health/ready && curl -s http://localhost:3000/health
```

期望三个服务都返回 `"status":"ok"`。`/health/ready` 会额外报告 PostgreSQL 与 Redis 连通性；任一依赖不可用时返回 503 且 `status` 为 `degraded`。

`/health/live` 不检查依赖——数据库故障不应让进程看起来已死。

## 4. 验证数据库迁移与 pgvector

```bash
docker compose -f infra/compose/docker-compose.yml exec postgres psql -U ai_hot_radar -d ai_hot_radar -c "SELECT extname FROM pg_extension WHERE extname='vector';" -c "\dt"
```

## 5. 规格校验

```bash
python scripts/validate_spec.py
```

校验 140 个信源、profile 引用完整性，以及 `verification: restricted` 的来源确实默认关闭。

## 6. 单独运行各服务

**ai-service**

```bash
cd apps/ai-service && pip install -e ".[dev]" && pytest -q
```

**core-api**

```bash
cd apps/core-api && mvn test
```

本地跑 Maven 需要 JDK 21（ADR-002）。当前机器上是 JDK 17，用 Docker 构建不受影响。

**web**

```bash
cd apps/web && npm install && npm run dev
```

## 7. 停止与清理

```bash
docker compose -f infra/compose/docker-compose.yml down
```

加 `-v` 会一并删除 PostgreSQL 数据卷（清空所有采集数据）：

```bash
docker compose -f infra/compose/docker-compose.yml down -v
```

## 8. 重要约定

- **数据库变更只能通过 Flyway**（`AHR-SPEC-000` §8）。迁移文件位于 `database/migrations/`，是 Java、CI 和文档共用的唯一入口，禁止手工改表。
- **密钥只进 `.env`**，仓库只提交 `.env.example`。
- **request ID 跨服务传递**：三个服务都接受并回显 `X-Request-ID`，缺失时自动生成，并写入结构化日志。
- **M0 不写业务页面**。首页、详情、Story 等从 M2 开始。

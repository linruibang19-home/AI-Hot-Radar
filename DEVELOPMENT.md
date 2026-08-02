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

## 6. 运行测试

三套测试都能在 Docker 里跑，不依赖本机装了什么运行时。

**ai-service（213 个用例）**——`--network none` 是刻意的：AHR-QSO-700 §1 要求测试回放 fixture 而不是访问真实站点，断网是唯一能证明这一点的方式。

```bash
docker build --target test -t ahr-test apps/ai-service
```

```bash
docker run --rm --network none -v "$PWD/config:/app/config:ro" ahr-test
```

**core-api（22 个用例）**——本机是 JDK 17，而 ADR-002 锁定 JDK 21，所以用镜像里的 JDK 跑：

```bash
docker run --rm -v "$PWD:/repo" -w /repo/apps/core-api maven:3.9-eclipse-temurin-21 mvn -B test
```

**web（12 个用例 + 类型检查）**

```bash
docker run --rm -v "$PWD/apps/web:/app" -w /app node:22-slim sh -c "npm ci && npx vitest run && npx tsc --noEmit"
```

本机若已装好对应运行时，也可以直接 `cd apps/ai-service && pip install -e ".[dev]" && pytest -q`、`cd apps/core-api && mvn test`、`cd apps/web && npm test`。

## 7. 单独运行各服务

```bash
cd apps/web && npm install && npm run dev
```

## 8. 停止与清理

```bash
docker compose -f infra/compose/docker-compose.yml down
```

加 `-v` 会一并删除 PostgreSQL 数据卷（清空所有采集数据）：

```bash
docker compose -f infra/compose/docker-compose.yml down -v
```

## 8. 采集操作

导入 140 个信源（幂等，可重复执行）：

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli sync-sources
```

探测信源并输出全文成功率报告：

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli probe --limit 20 --output /tmp/probe.json
```

`--profile github_release_api` 可只探测某一类。报告区分 `ACTIVE`（拿到真实全文）、`METADATA_ONLY`（只有摘要）、`DEGRADED`（全文失败）、`RATE_LIMITED`（配额耗尽，非故障）和 `QUARANTINED`（发现阶段就失败）。

**GitHub 未登录配额只有 60 次/小时**。在 `.env` 里设置 `GITHUB_TOKEN`（只读权限即可）后提升到 5000 次/小时，否则大批量探测会中途耗尽。

## 9. 常见问题

**新增迁移后 core-api 启动失败**：迁移文件是在**构建时**拷进镜像的，改了 `database/migrations/` 必须重建：

```bash
docker compose -f infra/compose/docker-compose.yml up -d --build core-api
```

**Flyway 报 "Found non-empty schema but no schema history table"**：说明有人用 `psql` 手工执行过迁移。Flyway 必须独占管理 schema，清空数据卷重来：

```bash
docker compose -f infra/compose/docker-compose.yml down -v && docker compose -f infra/compose/docker-compose.yml up -d --build
```

**宿主机 5432 端口被本地 PostgreSQL 占用**：容器内部通信不受影响。需要直连时用 `docker compose exec postgres psql -U ai_hot_radar -d ai_hot_radar`。

## 10. 重要约定

- **数据库变更只能通过 Flyway**（`AHR-SPEC-000` §8）。迁移文件位于 `database/migrations/`，是 Java、CI 和文档共用的唯一入口，禁止手工改表。
- **密钥只进 `.env`**，仓库只提交 `.env.example`。
- **request ID 跨服务传递**：三个服务都接受并回显 `X-Request-ID`，缺失时自动生成，并写入结构化日志。
- **M0 不写业务页面**。首页、详情、Story 等从 M2 开始。

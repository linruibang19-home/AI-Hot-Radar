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

**ai-service（510 个用例）**——`--network none` 是刻意的：AHR-QSO-700 §1 要求测试回放 fixture 而不是访问真实站点，断网是唯一能证明这一点的方式。

```bash
docker build --target test -t ahr-test apps/ai-service
```

```bash
docker run --rm --network none -v "$PWD/config:/app/config:ro" ahr-test
```

**core-api（30 个用例）**——本机是 JDK 17，而 ADR-002 锁定 JDK 21，所以用镜像里的 JDK 跑：

```bash
docker run --rm -v "$PWD:/repo" -w /repo/apps/core-api maven:3.9-eclipse-temurin-21 mvn -B test
```

**web（36 个用例 + 类型检查）**

```bash
docker run --rm -v "$PWD/apps/web:/app" -w /app node:22-slim sh -c "npm ci && npx vitest run && npx tsc --noEmit"
```

**web E2E（28 个用例，Playwright）**——需要整套 Compose 已经在跑，因为它测的是真实浏览器行为：

```bash
docker run --rm --network host -v "$PWD/apps/web/e2e:/e2e" -w /e2e mcr.microsoft.com/playwright:v1.49.1-noble sh -c "npm install --silent && npx playwright test"
```

这套用例存在的理由很具体：全部 AI 动态的三个缺陷**全部躲过了单元测试和服务端 HTML 检查**
——「加载更多」替换而非追加、折叠的 `<details>` 吞掉追加的内容、按条数分页而页面按天组织
（8-3 有 192 条，要点八次才能看到 8-2）。三个都是浏览器行为，三个都上线了。

三个 spec 各管一件事：

| 文件 | 用例 | 覆盖 |
|---|---:|---|
| `items-feed.spec.ts` | 7 | 按天全展示、折叠懒加载、不重复 |
| `ask.spec.ts` | 6 | SSE 进度先于答案到达、阶段顺序、引用可点、拒答是合法结果 |
| `navigation.spec.ts` | 15 | 8 个页面逐页点检 + **console error 即失败**、详情/返回、375px 无横向溢出 |

`navigation.spec.ts` 把 console error 当失败是刻意的：一个渲染成功、
状态码 200、但控制台在报客户端 fetch 失败的页面，用状态码检查不出来。
它上线第一次跑就抓到了全站在 375px 下横向溢出（侧边栏拖拽手柄挂在视口外 3px）。

**Playwright 刻意不放进 `apps/web/package.json`**。放进去会进入运行时镜像的 `npm ci`，
并且因为 `next build` 会类型检查整棵树，构建会因为一个服务器永远不会执行的 import 而失败。
它有独立的 `apps/web/e2e/package.json`，官方镜像已自带浏览器。

本机若已装好对应运行时，也可以直接 `cd apps/ai-service && pip install -e ".[dev]" && pytest -q`、`cd apps/core-api && mvn test`、`cd apps/web && npm test`。

> **Windows 上带挂载的 `docker run` 请用 PowerShell，不要用 Git Bash。**
> MSYS 会把 `-v "$PWD/apps/web/e2e:/e2e"` 里的路径改写成 Windows 形式，
> 结果是容器挂载失败，并在仓库里留下一个名叫 `e2e;D` 的空目录。
> 这个坑已经踩到两次，`.gitignore` 里加了 `*;D/` 兜底，但正确做法是换 shell。

## 6.5 连接数据库（Navicat / psql）

容器的 PostgreSQL 映射在宿主机 **5433**，不是 5432——本机若装了 PostgreSQL 服务
会同时占用 5432，客户端连过去会落到错误的实例上，而 PostgreSQL 对「角色不存在」
和「口令错误」返回同一句 `password authentication failed`，排查时极易误判。

| 字段 | 值 |
|---|---|
| 主机 / 端口 | `localhost` / **`5433`** |
| 初始数据库 | `ai_hot_radar` |
| 用户名 | `ai_hot_radar` |
| 密码 | 见根目录 `.env` 的 `POSTGRES_PASSWORD` |

本项目没有创建 `postgres` 超级用户，用它连必然失败。
端口可用 `POSTGRES_HOST_PORT` 覆盖。

## 7. 后台常驻服务

两个 worker，分工不同：

| 服务 | 间隔 | 职责 |
|---|---|---|
| `scheduler` | 120s | 只做采集：轮询到期信源、抓取入库 |
| `pipeline` | 900s | 采集之后的全部环节：结构化 → 聚类 → 精选 → 推荐理由 → 报告 |

两者都随 `docker compose up -d` 自动启动。手动跑一趟加工：

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli pipeline --once
```

`pipeline` 用 Postgres advisory lock 保证不会有两趟重叠——一趟实测约 6 分钟，
超过间隔时重叠会对同一批内容重复调用 LLM。

## 8. 单独运行各服务

```bash
cd apps/web && npm install && npm run dev
```

## 9. 停止与清理

```bash
docker compose -f infra/compose/docker-compose.yml down
```

加 `-v` 会一并删除 PostgreSQL 数据卷（清空所有采集数据）：

```bash
docker compose -f infra/compose/docker-compose.yml down -v
```

## 10. 采集操作

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

## 11. 常见问题

**新增迁移后 core-api 启动失败**：迁移文件是在**构建时**拷进镜像的，改了 `database/migrations/` 必须重建：

```bash
docker compose -f infra/compose/docker-compose.yml up -d --build core-api
```

**Flyway 报 "Found non-empty schema but no schema history table"**：说明有人用 `psql` 手工执行过迁移。Flyway 必须独占管理 schema，清空数据卷重来：

```bash
docker compose -f infra/compose/docker-compose.yml down -v && docker compose -f infra/compose/docker-compose.yml up -d --build
```

**宿主机 5432 端口被本地 PostgreSQL 占用**：容器已改为映射 **5433**，见 §6.5。
两者同时监听 5432 时客户端会落到错误的实例上，而 PostgreSQL 对「角色不存在」和
「口令错误」返回同一句 `password authentication failed`，看起来像是密码填错了。

## 12. 重要约定

- **数据库变更只能通过 Flyway**（`AHR-SPEC-000` §8）。迁移文件位于 `database/migrations/`，是 Java、CI 和文档共用的唯一入口，禁止手工改表。
- **密钥只进 `.env`**，仓库只提交 `.env.example`。
- **request ID 跨服务传递**：三个服务都接受并回显 `X-Request-ID`，缺失时自动生成，并写入结构化日志。
- **M0 不写业务页面**。首页、详情、Story 等从 M2 开始。

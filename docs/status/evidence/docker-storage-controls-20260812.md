# Docker 磁盘增长控制（2026-08-12）

任务卡：`TASK-M5-012`。

## 根因与边界

清理前运行容器可写层不足 1MB，主要占用为 45.02GB 镜像、24.74GB BuildKit 缓存和
7.66GB 本地卷。清理后只保留 AI Hot Radar 的运行容器、引用镜像、PostgreSQL 数据卷和
Redis 当前挂载卷；业务数据库未受影响。

## 持续控制

- 本地与生产 Compose 的每个服务统一使用 Docker `local` 日志驱动；
- 每个容器最多保留 3 个 10MB 压缩轮转日志；
- `infra/scripts/docker-desktop-maintenance.ps1` 把 BuildKit 缓存控制在 5GB，并清理七天以上、
  未被任何容器引用的镜像；
- Windows 计划任务 `AI Hot Radar Docker Maintenance` 每天 03:15 执行；Docker Desktop
  未运行时安全跳过；
- 自动维护明确不调用 `docker volume prune`，PostgreSQL 仍是唯一事实源。

日志配置只对重新创建的容器生效。宿主 `docker_data.vhdx` 不会因内部删除自动缩小，物理收缩
仍需退出 Docker Desktop、关闭 WSL 并在单独维护窗口 compact VHDX。

## 验收

```text
docker compose -f infra/compose/docker-compose.yml config --quiet
PASS

AHR_ENV_FILE=<absolute fixture> docker compose --env-file \
  infra/compose/preflight.env.example -f infra/compose/docker-compose.prod.yml config --quiet
PASS

python -m pytest -q tests/test_prod_compose.py tests/test_production_delivery.py
PASS: 12 passed, 2 skipped（Windows 无 POSIX shell；Compose 结构检查已单独通过）

重建前后 `content_item`：2073 → 2075（采集继续运行，PostgreSQL 卷未丢失）
运行态：8/8 容器使用 `local`, `max-size=10m`, `max-file=3`；Web/Core/AI/PostgreSQL/Redis
健康，首页、报告、问答、AI live/ready 均返回 200。
```

# 压测与容量证据

每份文件必须写明日期、Git SHA、硬件/容器限制、数据规模、脚本、请求组合、持续时间、缓存冷热、
错误率和 P50/P95/P99。开发机用于修改前后回归；生产机只跑低并发只读验证；真正的容量上限应在
同规格隔离副本上阶梯寻顶和 soak。

- [`2026-08-13-local-baseline.md`](2026-08-13-local-baseline.md)：本地分层基线、RAG 统计瓶颈与修复前数据；
- `2026-08-14-m5-020-production.md`：TASK-M5-020 发布后补充的本地复测和香港 2C4G 低风险实测。

脚本入口：[`../../../infra/loadtest/README.md`](../../../infra/loadtest/README.md)。

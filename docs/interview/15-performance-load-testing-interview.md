# 性能压测面试手册

## 30 秒版本

项目不把健康检查吞吐当业务 QPS。主场景用 k6 混合 Web SSR、Core 公共 API 和 AI 只读健康路径，数据库和
缓存分别用 pgbench、redis-benchmark。2026-08-13 在 14 核开发机、Docker 约 15.35 GiB 条件下，20 VU、
90 秒的第一版完成 12,407 请求，约 123.9 req/s，错误率 0、总体 P95 209 ms；Core P95 41.6 ms，Web
P95 510 ms。把 Python health 换成真正的 `/rag/stats` 后，复跑降到 66.3 req/s，AI 控制路径 P95 919 ms
并触发 750 ms 失败门；第二次完整复跑 AI P95/P99 为 838/4046 ms，再次红灯。这是能发现瓶颈的回归
基线，不是 2C4G 生产容量。

## 3 分钟版本

1. 先定义读路径 SLO：Core P95 <750 ms、SSR P95 <1.5 s、错误率 <1%；
2. smoke 只验证脚本，baseline 阶梯升并发并为 Web/Core 分标签；
3. 同步观察 docker stats、Hikari 连接池、PostgreSQL 连接/锁/buffer、Redis eviction/hit、Python worker；
4. pgbench 复现代表性已发布内容流 SQL，Redis benchmark 只作为原语上限；
5. 生成/Embedding/rerank 不直接打付费 provider，而是 mock/replay 测系统，再用小流量 canary 测供应商；
6. 以满足 SLO 的最高稳定档为容量，保留至少 30% 余量，并做长时间 soak 找泄漏。

脚本：`infra/loadtest/read-paths.js`、`infra/loadtest/postgres-feed.sql`；证据：
`docs/status/loadtest/2026-08-13-local-baseline.md`。

## 高频追问

### Q1：为什么用 k6，不用 wrk 或 ab？

k6 可以版本化多 endpoint、阶段、标签、检查和阈值。wrk2 适合 Linux 恒定到达率的单端点极限，可补充；
ab 只适合非常简单的烟测。工具不是重点，重点是请求组合、正确性断言和观测完整。

### Q2：VU、QPS 和并发是什么关系？

VU 是并发执行者，不等于 QPS。闭环模型中每个 VU 完成一次迭代才发下一次，QPS 受响应时间和 think time
影响。需要模拟固定进入速率时应用 k6 constant-arrival-rate，避免服务变慢后发生率自动下降。

### Q3：为什么必须看 P95/P99？

平均值会掩盖冷缓存、连接池排队、GC 和外部调用长尾。本次总体 max 超过 3 秒而 P95 仍是 209 ms，说明只
报平均或 P95 都可能漏掉极端请求；生产需要 P99、超时率和 trace 联查。

### Q4：pgbench 12k TPS 是否说明数据库能扛 12k QPS？

不能。那是热缓存、单条代表 SQL、10 客户端的组件基线，不包含多个查询、JSON 序列化、网络、事务写入和
锁冲突。它用于排除数据库原语瓶颈和比较索引变化，不等于网站业务容量。

### Q5：Redis 70k req/s 有什么意义？

只说明本机 PING/网络/单实例原语没有明显异常。业务性能还取决于序列化、key 大小、TTL、命中率和击穿。
当前 Redis 没有内存上限，因此迁移到 2C4G 前要设置预算和 eviction/oom 告警。

### Q6：Java 侧重点看什么？

Hikari 当前最大池约 10；看 active/pending、获取连接耗时、Tomcat 线程、GC、CPU 和接口标签 P95。连接池不应
盲目调大：PostgreSQL 连接有成本，若 SQL 很快而 SSR 慢，增大池不会解决前端请求瀑布。

### Q7：Python 侧重点看什么？

当前 Uvicorn 单 worker，区分 CPU 解析、数据库等待和外部 provider 等待；查看 event loop 堵塞、连接池、
超时、重试和各阶段 P95。要扩 worker 时先确认内存和任务幂等，避免每个 worker 重复调度。

### Q8：如何压测 RAG 又不花掉 API 预算？

三层拆开：固定查询集压 retrieval-only；录制 reranker/generator 响应作 replay 测并发与解析；最后少量真实
provider canary 测延迟/限流。每层同时记录检索质量和引用质量，不能用空模型换高吞吐。

### Q9：如何定位用户说“点按钮卡”？

先用浏览器 Network/trace 区分导航、SSR、API 和渲染；再用 k6 相同 endpoint 重现，并对 Web/Core 分标签。
本地数据显示 Web P95 510 ms、Core 42 ms，优先检查 SSR 请求串行、冷缓存和页面数据重复，而不是先换数据库。

### Q10：2C4G 上怎么做容量验收？

恢复脱敏生产副本，使用同 SHA 镜像和容器资源限额；冷/热两组、阶梯 5–10 分钟、1–2 小时 soak；达到错误率
或 P95 门就停止。最高稳定档减去 30% 余量后才是规划容量。不能从 14 核开发机线性除以 7 推算。

## 简历数字写法

可以写：

> 建立 k6 + pgbench + redis-benchmark 分层基线；在 14 核本地 Docker 环境以 20 VU 混合读场景完成
> 首轮 12,407 请求、0 错误；在加入真实 RAG 统计聚合后识别其 P95 919 ms 越过 750 ms 门，
> 同轮 Core P95 47 ms、Web P95 528 ms，据此建立可复现性能待办而非虚报生产 QPS。

不能写：

> 系统线上支持 124 QPS，数据库支持 12k QPS。

后一句没有生产同规格环境、SLO 和持续测试证据，面试追问会立即失守。

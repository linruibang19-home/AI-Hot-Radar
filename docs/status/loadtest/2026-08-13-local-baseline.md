# 2026-08-13 本地分层读路径容量基线

## 结论先行

这是一组**开发机 + 本地 Docker Desktop** 基线，不是香港 2C4G 生产容量承诺。标准脚本不访问
公网、不调用 DeepSeek、Embedding 或 Reranker，也不写业务表。它回答的是“当前只读链路在可复现
环境下哪里先变慢”，不能回答“线上最多支撑多少用户”。

第一版端到端混合读流量在最高 20 VU、90 秒爬坡中完成 12,407 个 HTTP 请求，失败 0 个，平均
123.89 req/s；总体 p95 209.32 ms。Core API 自定义采样 p95 41.62 ms，Web SSR p95
510.15 ms。该版 Python 腿只检查 readiness。随后把它升级为真正读取 `/rag/stats` 的本地
PostgreSQL/RAG 控制路径：2026-08-14 复跑 6,849 请求、0 错误、66.34 req/s，Core p95
46.59 ms、Web p95 528.41 ms，但 AI 控制路径 p95 918.94 ms，越过 750 ms 门，整轮按失败退出。
这说明 RAG 统计聚合是本地读路径的首个明确容量边界，不能把第一版较高吞吐继续当作完整基线。

## 环境

| 项目 | 本次值 |
|---|---|
| 日期 | 2026-08-13，Asia/Shanghai |
| Git | `2502274` / `v0.1.11`，分支 `codex/m5-019-docs-loadtest` |
| 主机 | Intel Core Ultra 5 125H，14 核 / 18 逻辑处理器 |
| Docker 可见内存上限 | 约 15.35 GiB |
| 运行方式 | `infra/compose/docker-compose.yml`，8 个业务容器 |
| Java | Spring Boot 3.4，Hikari 最大连接池 10 |
| Python API | Uvicorn 单 worker；Scheduler/Pipeline 为独立进程 |
| 数据 | 2,241 条本地内容；9,184 个活跃 chunk，9,184 个有 embedding |

开发机 CPU 核数远高于生产 2C4G，因此这里的吞吐**只能做修改前后对照**。

本次附带的 chunk 审计还发现：本地库有 5 个旧算法遗留的活动块超过当前 1200 token 硬上限；
对同一 revision 用当前 `chunk_document()` 重跑后最大值能够回到 1200 以内。这不是本轮压测产生的
数据错误，也没有在文档任务中静默修改数据库。生产 V026 版本化重切后的活动超长块为 0；本地若要
与生产一致，需要显式运行版本化 re-chunk maintenance，而不是覆盖历史引用。

## HTTP 结果

命令：

```powershell
docker run --rm `
  -e BASE_URL=http://host.docker.internal:3000 `
  -e CORE_URL=http://host.docker.internal:8080 `
  -e AI_URL=http://host.docker.internal:8000 `
  -v "${PWD}/infra/loadtest:/scripts:ro" `
  grafana/k6:0.55.0 run /scripts/read-paths.js
```

当前工作负载每轮并发读取 5 个 Core API 端点、1 个轮换 Web SSR 页面、1 次 Python `/rag/stats`，
轮次间 sleep 200 ms。阶段为 5 → 10 → 20 → 0 VU，共 90 秒。

| 指标 | 结果 |
|---|---:|
| HTTP 请求 | 12,407 |
| 失败率 | 0.000% |
| 平均请求率 | 123.890 req/s |
| 总体 avg / p95 / max | 53.16 / 209.32 / 3,380 ms |
| Core API avg / p95 / max | 17.83 / 41.62 / 3,230 ms |
| Web SSR avg / p95 / max | 187.60 / 510.15 / 3,280 ms |
| 迭代 p95 | 909.28 ms |

一轮有 7 个 HTTP 请求，所以 `123.89 req/s` 不是 123.89 个完整用户动作/秒。完整混合轮次为
17.69 iteration/s。最大值超过 3 秒但 p95 仍低，说明还存在少量调度、GC、首次编译或连接竞争
造成的长尾；需要更长 steady-state 和资源隔离实验才能定位。

### 增加真实 Python RAG 控制路径后的基线

| 指标 | 2026-08-14 复跑 |
|---|---:|
| HTTP 请求 / 完整迭代 | 6,849 / 978 |
| 失败率 / 业务检查 | 0.000% / 100% |
| HTTP / 完整迭代吞吐 | 66.34 req/s / 9.47 iteration/s |
| 总体 avg / p95 / max | 112.21 / 560.88 / 5,489 ms |
| Core API avg / p95 / max | 18.52 / 46.59 / 95.06 ms |
| Web SSR avg / p95 / max | 214.27 / 528.41 / 4,991 ms |
| AI `/rag/stats` avg / p95 / max | 478.91 / **918.94** / 5,489 ms |

只有 `ai_control_latency p95 < 750 ms` 失败，HTTP 状态和全部业务检查均通过。不能靠把门调到
1000 ms 让结果“变绿”：下一步应先 profile `retrieval_summary` 的聚合 SQL、缩短统计窗口或增加
可失效的只读聚合缓存，再用同一脚本复测。第一版与复跑都保留，恰好说明为什么压测脚本必须覆盖
真实业务 SQL，而不能只压 health。

为补齐 P99，2026-08-14 最后一轮同配置得到 6,926 请求、69.00 req/s、0 错误：总体
P95/P99 为 571.18/802.79 ms；Core 为 42.86/56.04 ms；Web 为 511.23/596.27 ms；
AI `/rag/stats` 为 **837.99/4046.49 ms**。AI P95 连续两轮分别为 918.94 和 837.99 ms，
说明超门可重复；P99 约 4 秒说明少量聚合请求存在明显长尾，TASK-M5-020 必须先 profile 再优化。

## PostgreSQL 结果

`infra/loadtest/postgres-feed.sql` 模拟公开 feed 的只读分页：过滤 duplicate、按发布时间与 id
倒序取 20 条。10 client、2 thread、30 秒：

| 指标 | 结果 |
|---|---:|
| transactions | 366,450 |
| failed | 0 |
| avg latency | 0.818 ms |
| TPS | 12,220.34 |

这是**单条热数据 SQL 的数据库 TPS**。数据和索引都能进页缓存，没有 JSON 组装、网络代理、Java
DTO、SSR，也没有 RAG 向量查询；绝不能把它写成网站 QPS。`pgbench` 因数据库没有标准
`pgbench_*` 表会打印 vacuum warning，但自定义查询照常运行，不影响这组统计。

## Redis 结果

为避免污染应用 cache，仅运行 PING：20 client、100,000 请求。

| 协议 | ops/s | p50 |
|---|---:|---:|
| inline | 78,802 | 0.103 ms |
| multibulk | 63,980 | 0.119 ms |

这只是本机网络与 Redis event loop 上限，不包含序列化、Spring Cache key、RAG 语料指纹或
回源数据库成本。当前本地 Redis 为无持久化、`maxmemory=0/noeviction`；业务正确性不依赖它，
但生产需要通过容器 memory limit 与告警防止缓存无限增长。

## 容器观察

压测期间抽样峰值约为：Web 114% CPU / 317 MiB，Core API 106% / 525 MiB，PostgreSQL
47% / 242 MiB，Redis 5% / 8 MiB。Python API 即使只走 readiness 也有容器调度噪声；本轮没有
对 AI 生成路径施压。

## 可以和不可以怎样讲

- 可以：第一版开发机混合流量 0 错误、约 124 HTTP req/s；加入 `/rag/stats` 后约 66 HTTP req/s，
  AI 控制路径 p95 919 ms 并触发失败门；
- 可以：Core API 热读 p95 42 ms，PostgreSQL 代表性 feed SQL 热缓存约 12.2k TPS；
- 不可以：项目支持 12,000 QPS；
- 不可以：2C4G 生产可以支撑 124 QPS；
- 不可以：RAG 首问也只有 209 ms，本轮根本没有调用模型。

下一轮生产前容量验收应在与目标机同规格的隔离环境做 15 分钟恒定负载、阶梯寻顶、30 分钟
soak，并独立测 RAG cache hit 与受控 provider stub；公开生产域名只允许低频 smoke。

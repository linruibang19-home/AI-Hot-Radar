# TASK-M5-020：RAG 统计修复与香港 2C4G 验证

## 状态

- 本地根因、修复和同场景回归：完成；
- GitHub Actions、GHCR 三镜像与香港生产部署：完成；
- 香港生产低风险只读验证：完成；
- 同规格隔离副本的容量寻顶与 1–2 小时 soak：未做，不能声称生产最大 QPS。

## 根因与修复

`GET /rag/stats` 在 FastAPI async route 内用同步 psycopg 连续执行 cost、latency、retrieval 和 corpus
聚合。SQL 单测很快，但并发请求占住唯一 event loop 并重复计算相同 30 天窗口，形成 4 秒 P99。

修复没有改 RAG 检索策略或事实来源：

1. 同步数据库聚合放入 `asyncio.to_thread()`；
2. 相同天数窗口在进程内 single-flight，冷启动只允许一次聚合；
3. 快照进入 Redis 30 秒，失败时回源 PostgreSQL；
4. 只缓存运营读模型，不缓存发布门判断或生成事实。

## 本地证据

| 项目 | 结果 |
|---|---:|
| 20 VU 混合 HTTP | 15,536 请求，154.91 req/s，0 错误 |
| AI `/rag/stats` | P95 11.21 ms，P99 18.77 ms |
| 修复前 AI | P95 837.99 ms，P99 4046.49 ms |
| RAG retrieval 四 SQL/事务 | 1,080.37 TPS，平均 9.256 ms，0 失败 |
| Redis PING | 84,890 inline / 75,758 multibulk ops/s |
| Redis 应用观察 | 1.47 MiB，0 eviction；累计 hit/miss 49,864/202 |

本地 smoke 复核 374 请求、27.59 req/s、0 错误；AI P95 4.60 ms，Core 7.61 ms，Web 58.00 ms。

## 香港生产证据

使用 `infra/loadtest/run-production-readonly.sh`，在 Compose 内部网络执行 1→2→5 VU，共 60 秒。
该脚本不访问公网、不写业务表、不调用 DeepSeek/SiliconFlow/SMTP；pgbench 仅执行两个版本化只读
SQL，Redis benchmark 仅 PING。

### 环境和版本

- 时间：2026-08-14 CST；
- 服务器：香港 Ubuntu 22.04，2C4G 套餐（系统可见 3.4 GiB），40 GiB 系统盘；
- Git/镜像：`ba5cfbeb1c1bd581cd95f4fa5c761fd1bb8bfc22`，三张业务镜像均为同 SHA tag；
- 数据：140 个信源、2266 条内容、9261 个 chunk（9261 已向量化）、1832 个 Story、
  229 次 RAG 问答、987 条引用、17 份报告；
- 发布前 preflight 通过，发布后 10 个容器健康，公开 smoke 全部通过。

### 结果

| 层 | 负载 | 结果 |
|---|---|---:|
| 混合 HTTP | 1→2→5 VU、60 秒 | 1536 请求，25.09 req/s，0 HTTP/业务错误 |
| AI `/rag/stats` | 同轮 | avg 8.88 ms，P95 10.69 ms，P99 126.93 ms |
| Core 公共读 API | 同轮 | avg 44.01 ms，P95 96.82 ms，P99 175.68 ms |
| Web SSR/代理 | 同轮 | avg 286.68 ms，P95 644.09 ms，P99 803.11 ms |
| PostgreSQL 内容流 SQL | 5 clients / 2 threads / 30 秒 | 741.02 TPS，平均 6.747 ms，0 失败 |
| PostgreSQL RAG 统计四查询 | 5 clients / 2 threads / 30 秒 | 79.43 TPS，平均 62.946 ms，0 失败 |
| Redis PING inline/multibulk | 50,000 / 10 clients | 40,355 / 45,413 req/s，P50 均 0.095 ms |

冷启动先删除唯一可再生的 `ahr:rag:v1:ops-stats:30`：冷读 164.3 ms，紧接热读 46.6 ms。
压测结束时该 key 的 TTL 为 `-2`，原因是后续 k6 与两轮各 30 秒 pgbench 已超过 30 秒 TTL；
它表示 key 已自然过期，不是 Redis 故障。Redis 当时 1.65 MiB / 128 MiB、`allkeys-lru`、0 eviction，
累计 hits/misses 为 3167/307；累计值不能冒充本轮命中率。

测试结束资源快照：PostgreSQL 294 MiB/640 MiB、Core API 260 MiB/512 MiB、Web 74 MiB/320 MiB、
AI Service 63 MiB/448 MiB、Redis 11 MiB/192 MiB；没有 swap、OOM 或容器重启。

## 判定和能说到哪里

低风险生产验证通过：修复后的 RAG 统计 P95 远低于 750 ms 初始门，公开读路径错误率为 0，
SSR P95 低于 1.5 秒初始门。25.09 req/s 是闭环 VU 请求组合在本轮的实际吞吐，不是最大容量；
741/79 TPS 是代表 SQL 的组件吞吐，4 万 req/s 是 Redis PING 原语吞吐，都不能写成网站 QPS。
真正容量仍需在同规格隔离副本上执行恒定到达率阶梯与 1–2 小时 soak。

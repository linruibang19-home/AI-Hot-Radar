# 21｜Redis：缓存、限流与短状态的完整边界

本项目只有一个事实源：PostgreSQL。Redis 7 用来减少重复读、供应商调用与匿名滥用，并保存可丢失的热状态。清空 Redis 应只带来一次数据库回源、更高延迟或额外模型费用，不能丢内容、订阅、报告、审核或历史问答。

## 1. 两个服务分别怎样使用 Redis

```text
Spring Boot Core API                         FastAPI AI Service
  ├─ 公共列表/统计 read-through cache          ├─ query embedding exact cache
  ├─ 主题/厂商地图 read-through cache           ├─ answer exact + semantic cache
  └─ Redis miss → PostgreSQL                   ├─ transcript 热副本 → DB fallback
                                               ├─ suggestions / ops snapshot
                                               └─ anonymous rate limit
                         Redis 7
                   （不保存业务事实）
```

## 2. Key、对象、TTL 与失败策略

| 所有者 | Key / cache name | 缓存什么，key 由什么组成 | TTL / 上限 | miss 或 Redis 故障时 |
|---|---|---|---|---|
| Java | `selected::*` | 精选列表、热点；天数/limit/content type/sort 等参数进入 key | 5 分钟 | 回 PostgreSQL；下一次重新填充 |
| Java | `topics::*` | category、topic map、vendor map、content type map | 10 分钟 | 回 PostgreSQL；允许短暂旧投影 |
| Java | `stats::*` | 首页统计、日期桶 | 2 分钟 | 回 PostgreSQL |
| Java | `reports::*` | 已配置 10 分钟 cache region | 10 分钟 | **当前没有 `@Cacheable` 报告入口使用它**；不能说报告已缓存 |
| Python | `ahr:rag:v1:embed:<digest>` | `model + 规范化问题` 的 query embedding | 7 天 | 重调 embedding provider |
| Python | `ahr:rag:v1:answer:<digest>` | 问题、corpus fingerprint、prompt version、answer pipeline version、时间窗对应的完整答案 | 1 小时 | 重新检索/重排/生成；拒答永不缓存 |
| Python | `ahr:rag:v1:semindex` | 最近问题向量与 answer key 的语义近邻目录 | 最多 200 条 | 线性扫描为空；转 exact miss 流程 |
| Python | `ahr:rag:v1:thread:<conversation>` | 最近对话 turns 的热副本 | 2 小时 | 回 PostgreSQL 读取 transcript |
| Python | `ahr:rag:suggest:<query_id>` | 某个已落库答案的追问建议 | 24 小时 | 从 PostgreSQL 读该轮引用并重新生成 |
| Python | `ahr:rag:v1:ops-stats:<days>` | `/ops` 固定时间窗聚合快照 | 30 秒 | 重跑 PostgreSQL 聚合 |
| Python | `ahr:rl:<caller>:m:<window>` | 匿名 IP 的分钟计数 | 60 秒固定窗口 | Redis 故障 fail-open |
| Python | `ahr:rl:<caller>:d:<window>` | 匿名 IP 的日计数 | 86,400 秒固定窗口 | Redis 故障 fail-open |
| Python | `ahr:rag:v1:hits` | exact/semantic/miss 等缓存命中计数 | 当前无 TTL | 只是运维统计，丢失不影响业务 |

TTL 都应从当前代码读取，不应从面试文档背诵成永恒常量。Java 在 `CacheConfig.java`，Python 在 `rag/cache.py`、`rag/api.py` 与 `rag/ratelimit.py`。

## 3. Java 公共读缓存如何工作

Spring Cache 使用 RedisCacheManager、字符串 key 和带类型信息的 JSON value。调用链是：

```text
GET /api/v1/content/selected?days=7&limit=20
  → @Cacheable 计算 selected::7:20:... key
  → hit：反序列化 DTO 返回
  → miss：ContentRepository 查询 PostgreSQL
           → DTO 写 Redis，TTL 5 分钟
           → 返回
```

为什么缓存空值被禁用：刚发布内容时一次空查询若被缓存，会在 TTL 内隐藏新内容。为什么类型白名单只允许项目包、`java.util`、`java.time`：Java record 需要类型信息才能从 JSON 还原，但开放任意 polymorphic type 会引入反序列化风险。

曾经出现过的真实故障是 record 在第一次 miss 时正常、第二次 hit 反序列化失败，导致 `/stats` 等接口 500。修复不是“前端兜底显示 0”，而是为最终 record 写入类型信息，并增加序列化 round-trip 测试。

### 缓存给谁

缓存的是 API 读模型，不是给某个登录用户的私有 session。当前站点是公共读场景，同参数请求共享一份条目；key 中包含会改变结果的查询参数，避免把一个分类/时间窗的结果返回给另一个。

### 如何失效

当前主要使用短 TTL，而不是每次内容写入时主动逐 key 驱逐。原因是采集持续发生、映射 key 多且公共读允许分钟级延迟；用 2–10 分钟自然过期比维护一套容易漏的失效广播更可靠。强一致事实仍直接查 PostgreSQL，Redis 不是发布状态判断依据。

## 4. RAG 为什么需要四种不同缓存

### 4.1 Query embedding：7 天 exact cache

同一模型与同一规范化问题的向量是近似纯函数。key 为 `model + canonical(question)` 的摘要；只折叠空白与大小写，不做 stemming，避免把词序/实体不同的问题错误合并。模型名变化天然 miss。

### 4.2 Answer exact cache：1 小时且与语料绑定

答案 key 同时包含：

```text
canonical(question)
+ corpus fingerprint
+ prompt_version
+ answer_pipeline_version
+ explicit time window
```

新内容使“最新动态”问题的 exact corpus fingerprint 改变，因此旧答案自动不可命中；解释/对比类问题使用按语料最新日期归一的 fingerprint，避免每两分钟来一篇无关文章都让稳定问题失效。后处理规则变化单独 bump `answer_pipeline_version`，不会谎称 prompt 改了，也不会浪费仍有效的 7 天 embedding cache。

拒答不缓存：拒答表达的是“现在证据库还没有答案”，恰好是最容易随新内容变化的结论。

### 4.3 Semantic near-match：0.97 门槛、同一语料指纹

exact miss 后可以在最多 200 个近期问题中做余弦相似度扫描，但只有相似度至少 0.97 且 corpus fingerprint 完全相同时才复用答案。0.85 这类演示阈值会把“DeepSeek 发布了什么”和“OpenAI 发布了什么”错误合并；这里宁可少命中，也不能把错误公司的答案高置信返回。

目录 list 本身是有界的但当前无 TTL；它保存的 answer key 会过期，旧目录项最终只造成一次 miss，不会返回已经消失的答案。若将来规模扩大，应换成带时间清理的 sorted set 或独立近邻索引，但当前 200 条线性扫描成本更低、行为更透明。

### 4.4 Transcript：2 小时热副本，数据库兜底

对话永久记录在 PostgreSQL。Redis 保存一个浏览会话附近的 turns，减少每轮都做多表 join。`None` 表示没缓存、要查库；空数组表示已经缓存且确实没有历史，这两个状态不能混淆。浏览器关掉后即使 Redis 过期，只要 permalink/对话 ID 仍存在，服务仍能从数据库恢复。

## 5. 匿名限流为什么 fail-open

公开问答一次会付 embedding、rerank、generation 的费用，所以默认每 IP 3 次/分钟、20 次/天。三个 Python 进程共享 Redis，不能用单进程内存计数，否则每个副本都会额外发一份额度。

固定窗口通过事务 pipeline 执行 `INCR + EXPIRE`。跨窗口边界可能短时使用两倍额度，这是为省去滑动日志每请求一条记录的成本而接受的取舍。Redis 故障时放行，因为这是一道成本保护，不是登录鉴权；让缓存重启导致整个问答下线会把受控费用风险升级为可用性事故。

## 6. Redis 没有做什么

- 不保存 `content_item`、revision、chunk、Story、报告、订阅、投递记录或管理审计的唯一副本；
- 不负责采集游标和 ETag；这些写 PostgreSQL，重启后仍能幂等继续；
- 不消费 `outbox_event`；当前后台任务是数据库轮询，不能包装成消息总线；
- 不做向量主库；embedding 落 pgvector，与 item/revision 的事务过滤共同查询；
- 不决定报告是否 PUBLISHED，也不决定邮件是否已发送；这些必须读 PostgreSQL 事实。

## 7. 运维检查与故障演练

生产检查避免使用阻塞式 `KEYS *`：

```bash
docker compose -f infra/compose/docker-compose.prod.yml exec redis \
  redis-cli INFO memory
docker compose -f infra/compose/docker-compose.prod.yml exec redis \
  redis-cli INFO stats
docker compose -f infra/compose/docker-compose.prod.yml exec redis \
  redis-cli --scan --pattern 'ahr:rag:*' | head
```

针对抽样 key 再使用 `TYPE`、`TTL`、`MEMORY USAGE`；不要把完整 answer/transcript 内容打印进公开日志。

恢复演练应验证：清空一个测试 namespace 后，公共 API 首次变慢但仍正确；RAG exact miss 后重新生成；transcript 从 PostgreSQL 恢复；限流计数丢失只暂时放宽额度。不要在生产高峰直接 `FLUSHALL`。

## 8. 面试深挖问答

**问：Redis 缓存的对象是谁的？**

答：Java 缓存公共 API 读模型，同参数用户共享；Python 缓存 query embedding、与语料指纹绑定的答案、对话热副本、建议和短 ops 聚合；限流按匿名 caller IP。所有持久事实仍在 PostgreSQL。

**问：为什么不是统一 5 分钟 TTL？**

答：对象的失效语义不同。embedding 由模型+文本决定可放 7 天；新闻答案随语料变化必须加 fingerprint 并只放 1 小时；ops 数字只为防刷新风暴放 30 秒；主题映射允许 10 分钟；对话热副本按一次浏览会话放 2 小时。

**问：缓存一致性怎么保证？**

答：业务正确性不依赖 Redis。公共读接受有界 TTL；RAG answer key 把 corpus/prompt/pipeline/window 都编码进 key；持久对话有 DB fallback；拒答不缓存。flush 只影响性能与费用。

**问：为什么语义缓存阈值是 0.97？**

答：实体不同的短问句在 embedding 空间可能很近，低阈值会复用错误主体的完整答案。这类错误不是质量稍降而是事实串线，所以使用高阈值、相同 corpus fingerprint 和 200 条有界索引。

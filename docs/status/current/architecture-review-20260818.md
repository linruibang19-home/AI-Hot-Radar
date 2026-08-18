# 架构与业务流程通读核查（2026-08-18）

> 本文是一次对 **代码 + 仓库 + 生产机** 三方的通读核查记录：逐层读源码梳理业务架构与技术
> 架构，再用香港生产机的只读查询验证「文档写的」和「线上跑的」是否一致。
>
> 核查范围：`apps/web`、`apps/core-api`、`apps/ai-service`、`database/migrations`、
> `infra/`、`config/`、`api/openapi.yaml`、`.github/workflows/`，以及生产机
> `/opt/ai-hot-radar` 的容器、镜像标签、Git HEAD 与 PostgreSQL 实查。
>
> 所有动态数字均标注了测量时刻，不构成实时承诺。当前基线仍以
> [`production-baseline.md`](production-baseline.md) 为准，本文只补充「通读结论」和
> 「新发现的偏差」。

---

## 1. 系统全景

### 1.1 进程拓扑（生产 10 个容器）

```text
                          Internet
                             │  HTTPS (Cloudflare → Full strict)
                             ▼
                    ┌─────────────────┐
                    │  caddy :80/:443 │  唯一发布端口，TLS 终结
                    └────────┬────────┘  trusted_proxies = Cloudflare 边缘段
                             │ reverse_proxy web:3000 (flush_interval -1 保 SSE)
                             ▼
                    ┌─────────────────┐
                    │  web  (Next 15) │  SSR + 同源 API 代理
                    └───┬─────────┬───┘
        公共读 / 订阅     │         │  RAG 问答 / 工程读视图
                        ▼         ▼
            ┌────────────────┐  ┌────────────────┐
            │ core-api :8080 │  │ ai-service:8000│
            │ Spring Boot 3.4│  │ FastAPI 3.12   │
            └───┬────────┬───┘  └───┬────────┬───┘
                │        │          │        │
                ▼        ▼          ▼        ▼
         ┌───────────┐  ┌──────────────┐
         │ postgres  │  │   redis 7    │   ← 只做缓存 / 限流 / 短锁
         │ 16+pgvector│ └──────────────┘
         └───────────┘
                ▲
   ┌────────────┼────────────┬─────────────┐
   │            │            │             │
scheduler    pipeline     backup        monitor
(采集循环)   (加工循环)   (每日 pg_dump) (健康+备份年龄告警)
   └── 三者共用 ai-service 镜像，只是 command 不同
```

关键结论：**没有消息队列、没有独立向量库、没有 K8s**。任务编排是
PostgreSQL 租约轮询（`FOR UPDATE SKIP LOCKED` + `next_poll_at`），向量检索是 pgvector，
稀疏检索是 PostgreSQL tsvector + CJK bigram 函数。`outbox_event` 表存在但**没有消费者**，
是预留而非已完成的消息总线（ADR-0028 已记录）。

### 1.2 服务职责边界

| 服务 | 拥有什么 | 明确不碰什么 | 入口文件 |
|---|---|---|---|
| `web` | 页面 SSR、同源代理、流式问答 UI | 直连数据库、持有可写管理凭据 | [`apps/web/src/lib/api.ts`](../../../apps/web/src/lib/api.ts) |
| `core-api` | 公共读 API、报告发布、订阅状态机、邮件投递、管理 RBAC/幂等/审计 | 网页抽取、embedding、检索算法 | [`ContentController.java`](../../../apps/core-api/src/main/java/com/aihotradar/coreapi/content/ContentController.java) |
| `ai-service` | 采集、正文抽取、LLM 结构化、Story 聚类、切块、向量、检索、生成、评测 | 用户权限、订阅业务事实、邮件状态机 | [`main.py`](../../../apps/ai-service/src/ahr/main.py) |
| `postgres` | 全部业务事实 + 向量 + 全文索引 | — | [`database/migrations/`](../../../database/migrations/) |
| `redis` | Spring 读缓存、RAG 答案/向量/会话热副本、匿名限流、30 秒统计快照 | 任何业务真相 | [`CacheConfig.java`](../../../apps/core-api/src/main/java/com/aihotradar/coreapi/cache/CacheConfig.java) |

Java / Python 的拆分是**按业务边界**而不是语言偏好：Java 拿事务、权限、交付语义；Python
拿变化快的采集、模型与评测。两侧唯一的共享面是 PostgreSQL 事实模型和 `api/openapi.yaml`
——它们之间**没有服务间 RPC**（`WORKER_BASE_URL` 已配置但当前无调用路径）。

---

## 2. 数据模型：为什么分这么多层

Flyway V001–V026，26 个迁移。核心链路上的表分层如下，每一层独立的理由都不是「规范好看」，
而是「合并了就会丢一种可追溯性」：

```text
source ──► crawl_run ──► raw_document ──► content_item ──► content_revision
  │                                            │                  │
  │                                            │                  ├──► content_chunk
  │                                            │                  │     (chunk_set_id + is_active)
  │                                            │                  │        │
  │                                            │                  │        ├─ embedding vector(1024)
  │                                            │                  │        └─ search_vector tsvector
  │                                            │                  │
  │                                            ├──► item_entity / item_topic / item_vendor_relation
  │                                            └──► story ──► story_item
  │                                                    │
  └──► source_health_daily                             └──► selection_record ──► report ──► email_delivery
                                                                                     │
rag_query ──► rag_citation ──► content_chunk (FK)                          report_subscription
     └──► rag_trace                                                             (双确认)
```

| 分层 | 不能合并的原因 |
|---|---|
| `content_item` / `content_revision` | 正文更新不能覆盖旧证据。旧回答引用的是**那一版**正文 |
| `content_chunk.chunk_set_id` + `is_active` | 重切块要新增一套并停用旧套，不能 DELETE——`rag_citation` 有 FK，删了要么违反外键，要么让旧回答指向不同证据（V026 / ADR-0031） |
| `story` / `story_item` | 去重后仍保留各家来源，`independent_source_count` 才有意义 |
| `report` + `status` 状态机 | 邮件和网页读同一份 `PUBLISHED` 快照，不在发送时重新生成（V022 / ADR-0025） |
| `report_subscription_request` vs `report_subscription` | 双确认：未确认的请求不是订阅 |
| `admin_idempotency` | 管理写操作重试不能重复产生审计和状态变更 |

**证据链的最小可核验单元是 `content_chunk` 的物理行**（ADR-0029）。AI 摘要写在
`content_item.summary_zh`，只用于阅读和结构化，**永远不能作为 RAG 的证据**。

---

## 3. 五条核心业务流程线

### 线 1：采集 → 入库（scheduler 容器，每 120 秒一 tick）

[`scheduler.py`](../../../apps/ai-service/src/ahr/ingestion/scheduler.py) →
[`pipeline.py`](../../../apps/ai-service/src/ahr/ingestion/pipeline.py)

```text
_claim_due_sources  ── FOR UPDATE SKIP LOCKED 抢占 next_poll_at 到期的源（batch=10）
   │                   多 worker 不会重复轮询；崩溃的 worker 只是让源重新到期
   ▼
build_adapter       ── 按 profile 分派 7 种 adapter：
   │                   github_release_api / github_repo_activity / arxiv_feed_paper
   │                   rss_to_article / docs_changelog / *_listing_to_article / public_json_api
   ▼
adapter.discover    ── 只拿发现元数据（RSS 摘要在这里止步，不冒充正文）
   ▼
_acquire_fulltext   ── 回源 canonical URL，trafilatura 抽正文
   ▼
fulltext_gate.evaluate ── 四道门：空正文 / 拦截页标记 / 长度（文章 300、release 80）
   │                      / 段落数 ≥2 / 链接密度 ≤0.35 / 元数据 ≥3 项
   │                      判定 ACCEPTED | METADATA_ONLY | REJECTED（三态，不是二值）
   ▼
persist_document    ── 逐文档 commit：一个坏页面不能回滚整轮
   ▼
状态裁决            ── 由 fulltext_attempt 表的历史证据决定源状态，
   │                   不是由本轮一次结果决定（这是修过的坑，见代码注释）
   ▼
save_cursor         ── 游标最后推进，且只记已 commit 的 external_id
```

失败退避：`consecutive_failures` 指数退避，上限 6 小时；健康的「本轮无新内容」不降级。

### 线 2：加工 → 产品出口（pipeline 容器，每 900 秒一遍）

[`worker.py`](../../../apps/ai-service/src/ahr/processing/worker.py) 用
`pg_try_advisory_lock` 保证同一时刻只有一遍在跑，然后**按依赖顺序**串行：

```text
process  → 切块（结构感知，目标 400 token / 硬上限 1200）
           simhash 近重复检测（14 天窗口，命中则标 duplicate_of_id 并跳过 LLM）
           DeepSeek 结构化 → Pydantic schema 校验 → zh_title/summary/实体/主题/质量分
           失败降级：schema 失败 → DEAD_LETTER；provider 不可用 → FAILED 且提前 break
embed    → bge-m3 补齐新 chunk 的向量（独立于生成模型，DeepSeek 挂了也跑）
cluster  → Story 聚类（标题相似 0.35 / 实体重叠 0.25 / 动宾 0.15 / 时间 0.10 / 主题 0.05）
           版本号硬规则否决合并：「DeepSeek V3」与「V4-Flash」不能并成一个事件
heat     → 热度重算 + 回写 content_item.hot_score
select   → 每日 12 条精选，单源 ≤3、单发布方家族 ≤3、research ≤4
           必须排在 cluster 之后，因为它读 story.independent_source_count
reasons  → LLM 写推荐理由（已有 reason_version 的不覆盖）
reports  → 日/周/月报，仅在有新 selection 时重算；当天日报 21:00 后才生成
```

> **切块不是对 AI 摘要再切一刀**——`chunk_current_revisions` 独立于 `enrichment_state`
> 运行，所以富化失败或被跳过的内容仍然可检索。这是修过的坑：早期把切块挂在 LLM 生命周期上，
> 重抓取推进 `current_revision_id` 后新正文永远不会被切。

### 线 3：RAG 问答（同步 / SSE 两条路，同一套验证）

[`service.py:answer_question`](../../../apps/ai-service/src/ahr/rag/service.py)

```text
POST /api/ask (Next 代理) → POST /rag/ask 或 /rag/ask/stream
   │
   ├─ 限流：Redis 匿名配额 3/min、20/day（fail-open）
   ├─ 预算：llm_usage 当日 token 天花板（fail-closed，503）
   ├─ 追问改写：多轮时先把「它呢」还原成独立问题（只给检索用，历史仍存原问）
   ├─ 元问题分流：「有哪些信源」直接答语料统计，不走检索
   ├─ 缓存两层：精确 key（语料指纹+prompt 版本+时间窗）→ 语义近邻（复用已嵌向量）
   │
   ├─ plan：问题类型 / 实体 / 时间范围 / 是否要求最新
   ├─ dense (60)  bge-m3 + pgvector <=> 余弦
   ├─ sparse (40) tsvector，IDF 加权求和（不是 ts_rank_cd），实体词 ×3
   ├─ temporal(40) 纯时间窗，每篇只取首块
   ├─ 别名扩展：vendor_entity 把「智谱」扩到 GLM / Zhipu
   ├─ RRF 融合 + §6 boost
   ├─ rerank：bge-reranker-v2-m3，深度按问题类型路由
   ├─ 维度重排（directness / source_fit）+ 时效重排（仅 freshness_required）
   ├─ 证据选取：单文档 ≤2、单来源 ≤3、Story 折叠、上限 10
   ├─ 父段扩展：喂给模型的是父块，引用仍绑在子块上
   │
   ├─ 生成：DeepSeek 受约束 JSON（answer_markdown + claims + limitations）
   ├─ 数值审计：命中「≥2 个数字 + 关系词」时追加一次受控审计调用，两次失败则 fail-closed
   ├─ bind_citations：只认真实召回的证据编号，伪造编号删除，按阅读序重编号
   ├─ 支持度：cross-encoder 打分，弱支持引用**删除**（不是仅标记）
   ├─ 无引用句删除 → 剩余孤儿引用一并删除
   ├─ check_invariants：4 条硬断言，违反即转拒答
   └─ 凭据输出保护：疑似 key/token 出现即阻断发布
```

**服务端约束优先于模型输出**：模型只返回候选声明和编号，URL、标题、来源、支持度全部由服务端
从数据库解析绑定。流式路径也走同一套绑定（`incremental.py`），不是「先给用户看再校验」。

### 线 4：报告 → 邮件（core-api，每 300 秒一轮）

[`ReportEmailDeliveryService.java`](../../../apps/core-api/src/main/java/com/aihotradar/coreapi/subscription/ReportEmailDeliveryService.java)

```text
Python 生成 report(status=DRAFT/REVIEW_REQUIRED/PUBLISHED)
   ▼
recoverStaleClaims   ── SENDING 超 15 分钟的回收为可重试或永久失败
enqueueLatestPublished ── 按订阅者时区本地时间 ≥ delivery_local_time，
   │                      且 published_at ≥ confirmed_at，且未投递过 → 插 email_delivery
   │                      唯一索引 (subscription_id, report_id) 保证不重发
claimDue             ── FOR UPDATE SKIP LOCKED 抢占，attempt_count+1
loadDeliverable      ── 再次校验 subscription ACTIVE + report PUBLISHED（否则 SKIPPED）
send → markSent / markFailed（重试 10min → 60min，3 次后 PERMANENT_FAILED）
```

订阅侧是**双确认**：`report_subscription_request`（24 小时过期、10 分钟内不重发确认信）
→ 确认后才写 `report_subscription`。退订令牌带 `token_version`，退订即版本+1 使旧链接失效。

### 线 5：管理面（RBAC + 幂等 + 审计）

`/api/v1/admin/**` 由 [`AdminAuthFilter`](../../../apps/core-api/src/main/java/com/aihotradar/coreapi/admin/AdminAuthFilter.java)
**按路径前缀**（不是按注解）拦截：Bearer token → `admin_principal` 解析角色 → 非 GET 需
`canMutate()`。拒绝一律返回同一句 `{"error":"forbidden"}`，不泄露失败原因。写操作要求
`Idempotency-Key` 并把响应存进 `admin_idempotency`。

web 容器持有的是 **VIEWER 角色**的只读 token——拿下 web 容器不等于拿下采集管道。

---

## 4. 中间件与横切关注点

| 关注点 | 实现 | 位置 |
|---|---|---|
| 缓存（Java） | Redis，TTL selected 5min / topics 10min / stats 2min / reports 10min；`disableCachingNullValues`；records 需 `DefaultTyping.EVERYTHING` 否则第二次读必炸 | `CacheConfig.java` |
| 缓存（Python） | 答案缓存 key 含**语料指纹**：要求时效的问题绑精确语料，其余绑「当天」 | `rag/cache.py:corpus_fingerprint` |
| 限流 | Redis `ahr:rl:{caller}:m:{minute}` / `:d:{day}`，fail-open | `rag/ratelimit.py` |
| 分布式互斥 | PostgreSQL `pg_try_advisory_lock`（pipeline）、`FOR UPDATE SKIP LOCKED`（scheduler / 邮件） | — |
| 外部调用约束 | 连接 5s / 读 20s 超时、有界重试、按 host 限速、trace id | `ingestion/http.py`、`config.py` |
| 可观测 | 结构化 JSON 日志 + `RequestIdFilter` / `RequestIdMiddleware`；OTel 可选（未设 endpoint 即 no-op）；`rag_trace` 表记录每次检索每个候选的去留原因 | — |
| 安全 | Caddy 安全响应头、HSTS、`/admin/` 不索引、SSRF 防护（`ingestion/ssrf.py`）、凭据输出阻断（`rag/safety.py`）、提示注入按数据处理（证据包在 `<UNTRUSTED_EVIDENCE>` 里） | — |

---

## 5. 仓库 ↔ 生产 对齐核查（2026-08-18 实测）

### 5.1 三方一致性

| 概念 | 值 | 结论 |
|---|---|---|
| GitHub `main` HEAD | `1cfdf1d`（CI actions 证据文档） | 领先生产 4 个提交，**全部是文档/CI** |
| 生产机 Git HEAD | `02e2d83`，工作树干净 | ✅ |
| 生产三张镜像 tag | `sha-02e2d83b5f7794b0ee4f6fc4193a8ff6f0cfb935` | ✅ 与 Git HEAD 同 SHA |
| 容器 | 10 个全部 Up，业务容器 19 小时前重启 | ✅ |
| Flyway | V026 | ✅ |

「服务器 = 生产版本，GitHub main 可能超前于生产」这条文档纪律**核实为真**，
且超前的部分不含业务代码。

### 5.2 生产数据实查（vs 08-17 基线）

| 指标 | 08-17 基线 | 08-18 实测 | 变化 |
|---|---:|---:|---|
| 登记信源 / 可调度 / ACTIVE | 143 / 131 / 110 | 143 / 131 / **109** | ACTIVE −1（另有 14 PROBING、5 QUARANTINED、0 DEGRADED） |
| 内容条目 | 2617 | **2729** | +112 |
| 已富化 | — | **2519** | 待处理 0、失败 0 |
| active chunk / 已向量化 | 11700 / 11700 | **12631 / 12631** | 无向量缺口 |
| Story | 2142 | **2246** | +104 |
| 报告 / 已发布 | 21 | **22 / 22** | 全部 PUBLISHED |
| RAG 问答 / 引用 | 232 / 990 | 232 / 990 | 近一日无新提问 |
| 活跃订阅 / 已发邮件 | — | 2 / 10 | 无 pending、无永久失败 |
| 最新内容 observed_at | — | 2026-08-18 04:49 UTC | 采集在跑 |
| 近 7 天 LLM token | — | 约 550 万 | 日均远低于 200 万上限 |

资源：磁盘 40G 用 19G（51%），内存 3495MB 用 1295MB，swap 未动。备份最新一份
`ai_hot_radar-20260817T104556Z.dump`（191 MB）+ SHA256，落在 26 小时告警阈值内。

pipeline 每遍 31–135 秒，scheduler 每 tick claimed 4–10、failed 0–1。**没有积压，没有错误堆积。**

---

## 6. 本次通读发现的偏差

按影响排序。三条都不是「正在坏」，但前两条是会被面试官或搜索引擎发现的。

### ① `robots.txt` 对外发布了 `http://localhost:3000/sitemap.xml`

> **已修复。** 采用了下面的推荐方案（`robots.ts` 加 `force-dynamic`），随 v0.1.19 于
> 2026-08-18 上线。部署后实查返回 `Sitemap: https://aihotradar.online/sitemap.xml`。
> 另加了一条测试，要求 `robots.ts` 与 `sitemap.ts` 都声明 `force-dynamic`。
> 本节保留通读当时的原始记录。

```bash
curl -s https://aihotradar.online/robots.txt
```

返回：

```text
User-Agent: *
Allow: /
Disallow: /admin/

Sitemap: http://localhost:3000/sitemap.xml
```

原因：[`apps/web/src/app/robots.ts`](../../../apps/web/src/app/robots.ts) 读
`process.env.PUBLIC_BASE_URL`，但它是**静态路由**，Next 在 `docker build` 阶段
（GitHub Actions 容器内，`PUBLIC_BASE_URL` 未设）就把结果烘焙进镜像了。同一个 `SITE_URL`
在 [`sitemap.ts`](../../../apps/web/src/app/sitemap.ts) 里正确，因为那个文件声明了
`export const dynamic = "force-dynamic"`。

同源问题的第二个表现：404 页（`/_not-found`，同样是构建期预渲染）的 `canonical` 与
`og:url` 也是 `http://localhost:3000`。首页等动态页正确。

修法二选一：给 `robots.ts` 加 `export const dynamic = "force-dynamic"`（与 sitemap 一致，
最小改动）；或在 `release.yml` 的 `docker/build-push-action` 加 `build-args` 并在
`apps/web/Dockerfile` 里 `ARG PUBLIC_BASE_URL`（同时修好所有构建期预渲染路由）。
推荐前者——它和 sitemap 的做法一致，不引入新的构建期变量。

### ② `api/openapi.yaml` 里的 RAG 契约与实现不符

契约 v1.6.0 声明 `POST /api/v1/rag/queries`（202 + 轮询 `GET /api/v1/rag/answers/{id}`），
但 core-api 里**没有任何 RAG 端点**（`grep @*Mapping` 可确认）。实际实现是
ai-service 的 `POST /rag/ask` 与 `POST /rag/ask/stream`，由 Next 的 `/api/ask` 同源代理，
并且是同步 + SSE，不是异步轮询。

这不影响运行——没有客户端在用那两个路径——但它让「OpenAPI 是跨语言契约」这句话在
RAG 这一块不成立。要么把这两条路径标 `deprecated` 并补上 ai-service 的真实契约，
要么删掉它们并在文档里说明 RAG 走独立服务。

### ③ 报告重算的触发条件偏粗

[`worker.py:_report_is_stale`](../../../apps/ai-service/src/ahr/processing/worker.py)
用「全局最新 `selection_record.created_at` > 该报告 `generated_at`」判定过期。任何一天出现
新精选，都会同时把日报、周报、月报三份判为过期并各花一次 LLM 调用。生产日志里能看到
`daily/weekly/monthly` 三个 `written` 总是同时出现。

当前体量下这是可接受的成本（近 7 天 550 万 token，上限 2000 万），记录在这里是因为它是
**内容量增长后第一个会超预算的地方**：把判据换成「该周期窗口内的最新 selection」即可，
不需要新表。

---

## 7. 通读后的整体判断

**架构是自洽的，不是拼出来的。** 三个可验证的迹象：

1. **每一个常量都有出处**。切块 400/1200 token、门禁 300/80 字符、融合权重、精选配额
   3/3/4、限流 3/20——代码注释里写的是「测出来是多少、改了会怎样」，不是「经验值」。
2. **失败分支被当成功能设计**。LLM 挂了站点降级不停摆、reranker 挂了记录降级不拒答、
   Redis 挂了限流 fail-open 但预算闸门 fail-closed、数值审计两次失败则不发布。
   每一条的方向都是想过的，不是默认值。
3. **负结果留在证据里**。B2 稀疏并集 MRR 从 0.7630 降到 0.7480、B8 权重扫描收敛到 0.0004
   因此维持现状——这两条被写成「记录为退化」而不是包装成优化。

**当前最大的真实边界**（已在 README「已知边界」里承认，此处只做确认）：

- `outbox_event` 有 1912 条未消费记录，是预留表而非消息总线；
- Gmail SMTP 只适合上线验证，没有 SPF/DKIM/DMARC；
- 无账号体系，`/history`、`/threads` 是**全站共享**的问答历史；
- 信源后台是数据库健康快照，不是实时告警台。

---

## 8. 建议的下一步

1. ~~修 `robots.ts` 的 `force-dynamic`~~ —— 已随 v0.1.19 上线，见发现 ①；
2. 对齐 `api/openapi.yaml` 的 RAG 契约（**未做**）；
3. 把报告过期判据收窄到周期窗口内（**未做**）；
4. 其余按 [`docs/spec/08-roadmap-ai-ide.md`](../../spec/08-roadmap-ai-ide.md) 的任务卡推进
   （当前为 `TASK-M5-030`）。

---

## 核查方法附录

生产侧全部为只读命令：

```bash
docker compose -f infra/compose/docker-compose.prod.yml ps
docker compose -f infra/compose/docker-compose.prod.yml logs --tail 15 pipeline
docker compose -f infra/compose/docker-compose.prod.yml exec -T postgres \
  psql -U ai_hot_radar -d ai_hot_radar -c "SELECT count(*) FROM content_item;"
```

未在生产机上写入任何数据、未修改任何配置、未重启任何容器。

# AI Hot Radar

> 从公开信源到可核验答案的一条完整数据链：持续采集 AI 行业资讯，整理成可订阅的情报产品，
> 并在同一份原文证据库上提供每句话都能回跳原文的 RAG 问答。

[![CI](https://github.com/linruibang19-home/AI-Hot-Radar/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/linruibang19-home/AI-Hot-Radar/actions/workflows/ci.yml)
[![Release](https://github.com/linruibang19-home/AI-Hot-Radar/actions/workflows/release.yml/badge.svg)](https://github.com/linruibang19-home/AI-Hot-Radar/actions/workflows/release.yml)
![Java 21](https://img.shields.io/badge/Java-21-orange)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)
![Next.js 15](https://img.shields.io/badge/Next.js-15-black)
![PostgreSQL 16 + pgvector](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791)

**线上地址** → **[aihotradar.online](https://aihotradar.online)**（真实运行，数据每天在长）

![精选首页：持续更新的 AI 情报、热点与推荐理由](docs/assets/screenshots/home.png)

---

## 目录

[这是什么](#这是什么) · [它是真的在跑](#它是真的在跑) · [核心业务流程](#核心业务流程) ·
[技术架构](#技术架构) · [数据模型](#数据模型为什么分这么多层) · [代码架构](#代码架构) ·
[三个工程决策](#三个工程决策) · [边界与取舍](#边界与取舍) · [深入阅读](#深入阅读) ·
[本地运行](#本地运行)

---

## 这是什么

AI 的新东西散落在官方博客、GitHub Release、arXiv 和几十家媒体里。同一件事被七八家转述，
你想知道的往往不是"有哪些新闻"，而是"这周到底发生了什么，以及我凭什么信"。

AI Hot Radar 做四件事：**采集正文 → 结构化并按事件聚合 → 生成日/周/月报 → 就这批语料回答问题**。
关键在最后一步：回答里的每一句事实都绑定到具体的原文片段，点击可以跳回原网页；证据不够时
系统拒答，而不是补一段听起来合理的话。

独立完成，2026-08-01 起 19 天，179 次提交，三个服务共 216 个源文件 + 28 个数据库迁移。

![RAG 问答：回答中的事实可回跳到原始证据](docs/assets/screenshots/rag-answer.png)

---

## 它是真的在跑

香港 2C4G 单机，Docker Compose 10 个容器，Caddy 提供 HTTPS，GitHub Actions 构建的不可变
`sha-<commit>` 镜像。

> 生产数据快照（2026-08-19，历史快照，非实时承诺）

| | |
|---|---:|
| 登记信源 / 允许调度 / 运行态 ACTIVE | 143 / 131 / 109 |
| 已入库内容（其中完成结构化） | 3044（2815） |
| 证据分块 / 已向量化 | 14602 / 14602 |
| 跨源聚合事件 Story | 2533 |

这些数字每天都在变。实时值看站内 [运行状态](https://aihotradar.online/ops) 页，或
[`docs/status/current/production-baseline.md`](docs/status/current/production-baseline.md)。

RAG 质量用固定的 90 题黄金集衡量，不用线上提问自评（2026-08-11 批次）：

| 指标 | 结果 | 它回答的问题 |
|---|---:|---|
| Recall@20 | `0.8994` | 正确证据有没有进前 20 候选 |
| 句级引用覆盖率 | `0.9881` | 有事实主张的句子是否都带引用 |
| 段落支持达标率 | `0.9344` | 引用的原文是否真的支持那句话 |
| 可回答题误拒 | `0 / 78` | 有证据时会不会错误拒答 |
| 诱导题错误断言 | `0 / 12` | 前提错误时会不会顺着编 |

逐轮实验产物在 [`docs/status/eval/`](docs/status/eval/)。换模型或改检索策略必须重跑，不沿用旧结论。

<details>
<summary>其余产品界面：日/周/月报 · RAG 质量门禁 · 信源后台</summary>

![报告页面](docs/assets/screenshots/reports.png)
![RAG 质量页面](docs/assets/screenshots/rag-quality.png)
![信源后台](docs/assets/screenshots/source-operations.png)

</details>

---

## 核心业务流程

### 一张图：从公开信源到可核验答案

```text
公开信源（RSS / API / HTML 列表 / GitHub / arXiv）
  │
  ▼
发现元数据 ──► 回源 canonical URL ──► 全文门（三态：ACCEPTED / METADATA_ONLY / REJECTED）
                                          │
                                          ▼
                        content_item ──► content_revision（正文版本化，不覆盖）
                                          │
              ┌───────────────────────────┴───────────────────────────┐
              ▼                                                       ▼
   LLM 结构化（Pydantic schema 校验）                    结构感知切块 → content_chunk
   zh_title / summary / 实体 / 主题 / 质量分              （chunk_set 版本化，引用绑在这里）
              │                                                       │
              ▼                                                       ▼
   Story 跨源聚类 ──► 精选评分（多样性配额）        bge-m3 向量 + tsvector 关键词索引
              │                                                       │
     ┌────────┼────────┐                                              ▼
     ▼        ▼        ▼                              dense / sparse / temporal 三路召回
  精选/热点 主题/事件 日周月报                                       │
     │                 │                                    RRF 融合 → cross-encoder 重排
     └────────┬────────┘                                              │
              ▼                                                       ▼
          网站读者 ◄──── 双确认邮件投递            服务端引用绑定 + 支持度校验 → 可核验回答
```

所有出口读取**同一份 PostgreSQL 已发布事实**。RSS 摘要只用于发现，不冒充正文；AI 生成的
摘要用于阅读和结构化，**永远不能作为 RAG 的证据**。

### 五条流程线

| 线 | 跑在哪 | 周期 | 入口文件 |
|---|---|---|---|
| 1 采集 → 入库 | `scheduler` 容器 | 120 秒 | [`ingestion/scheduler.py`](apps/ai-service/src/ahr/ingestion/scheduler.py) |
| 2 加工 → 产品出口 | `pipeline` 容器 | 900 秒 | [`processing/worker.py`](apps/ai-service/src/ahr/processing/worker.py) |
| 3 RAG 问答 | `ai-service` | 请求驱动 | [`rag/service.py`](apps/ai-service/src/ahr/rag/service.py) |
| 4 报告 → 邮件 | `core-api` | 300 秒 | [`ReportEmailDeliveryService.java`](apps/core-api/src/main/java/com/aihotradar/coreapi/subscription/ReportEmailDeliveryService.java) |
| 5 管理面 | `core-api` | 请求驱动 | [`AdminAuthFilter.java`](apps/core-api/src/main/java/com/aihotradar/coreapi/admin/AdminAuthFilter.java) |

#### 线 1：采集 → 入库

```text
_claim_due_sources   FOR UPDATE SKIP LOCKED 抢占到期的源（batch=10）
        │            多 worker 不重复轮询；崩溃的 worker 只是让源重新到期
        ▼
build_adapter        9 类采集 profile 分派到 7 种 adapter
        ▼
adapter.discover     只拿发现元数据 —— RSS 摘要在这里止步
        ▼
_acquire_fulltext    回源 canonical URL，trafilatura 抽正文，SSRF 防护 + 按 host 限速
        ▼
fulltext_gate        四道门：空正文 / 拦截页 / 长度（文章 300、release 80）/
        │            段落 ≥2 / 链接密度 ≤0.35 / 元数据 ≥3 项
        ▼
persist_document     逐文档 commit —— 一个坏页面不能回滚整轮
        ▼
状态裁决             由 fulltext_attempt 的历史证据决定源状态，不由本轮单次结果决定
        ▼
save_cursor          游标最后推进，且只记已 commit 的 external_id
```

全文门是**三态**而不是布尔值：`METADATA_ONLY` 的内容可以出现在列表页，但进不了 RAG 证据库。
失败退避按 `consecutive_failures` 指数增长、上限 6 小时；"本轮无新内容"是健康状态，不降级。

#### 线 2：加工 → 产品出口

`pg_try_advisory_lock` 保证同一时刻只有一遍在跑，然后**按依赖顺序**串行：

```text
process   切块（结构感知，目标 400 token / 最小 120 / 软上限 700 / 硬上限 1200 / 重叠 60）
          simhash 近重复检测（14 天窗口，命中即标记并跳过 LLM）
          DeepSeek 结构化 → Pydantic 校验 → schema 失败转 DEAD_LETTER，provider 挂了提前 break
embed     bge-m3 补齐新 chunk 向量 —— 独立于生成模型，DeepSeek 挂了这一步照跑
cluster   Story 聚类：标题相似 0.35 / 实体重叠 0.25 / 动宾 0.15 / 时间 0.10 / 主题 0.05
          版本号硬规则否决合并：「DeepSeek V3」和「V4-Flash」不能并成一个事件
heat      热度重算并回写 hot_score
select    每日 12 条精选，单源 ≤3、单发布方家族 ≤3、research ≤4
          必须排在 cluster 之后 —— 它读 story.independent_source_count
reasons   LLM 写推荐理由（已有 reason_version 的不覆盖）
reports   日/周/月报，仅在有新 selection 时重算
```

**切块不是对 AI 摘要再切一刀。** 切块独立于富化状态运行，所以富化失败或被跳过的内容仍然可检索。
这是修过的坑：早期把切块挂在 LLM 生命周期上，重抓取推进版本后新正文永远不会被切。

#### 线 3：RAG 问答

同步和 SSE 两条路，**共用同一套验证**——不是"先给用户看再校验"。

```text
POST /api/ask（Next 同源代理）→ /rag/ask 或 /rag/ask/stream
   │
   ├─ 限流    Redis 匿名配额 3/min、20/day（fail-open）
   ├─ 预算    当日 token 天花板（fail-closed，503）
   ├─ 改写    多轮时把「它呢」还原成独立问题（只给检索用，历史仍存原问）
   ├─ 分流    「有哪些信源」这类元问题直接答语料统计，不走检索
   ├─ 缓存    精确 key（语料指纹 + prompt 版本 + 时间窗）→ 语义近邻
   │
   ├─ plan       问题类型 / 实体 / 时间范围 / 是否要求最新
   ├─ dense 60   bge-m3 + pgvector 余弦
   ├─ sparse 40  tsvector，IDF 加权求和（不是 ts_rank_cd），实体词 ×3
   ├─ temporal 40 纯时间窗，每篇只取首块
   ├─ 别名扩展   vendor_entity 把「智谱」扩到 GLM / Zhipu
   ├─ RRF 融合 + 元数据 boost
   ├─ rerank     bge-reranker-v2-m3，深度按问题类型路由
   ├─ 证据选取   单文档 ≤2、单来源 ≤3、Story 折叠、上限 10
   ├─ 父段扩展   喂给模型的是父块，引用仍绑在子块上
   │
   ├─ 生成       DeepSeek 受约束 JSON（answer_markdown + claims + limitations）
   ├─ 数值审计   「≥2 个数字 + 关系词」时追加一次受控审计，两次失败即 fail-closed
   ├─ bind_citations  只认真实召回的编号，伪造编号删除，按阅读序重编
   ├─ 支持度     cross-encoder 打分，弱支持引用【删除】而不是仅标记
   ├─ 清理       无引用句删除 → 剩余孤儿引用一并删除
   ├─ 不变量     4 条硬断言，违反即转拒答
   └─ 凭据保护   疑似 key/token 出现即阻断发布
```

**服务端约束优先于模型输出**：模型只返回候选声明和编号，URL、标题、来源、支持度全部由服务端
从数据库解析绑定。模型没有机会写出一个 URL，所以它也无法伪造一条引用。

#### 线 4：报告 → 邮件

```text
Python 生成 report(DRAFT / REVIEW_REQUIRED / PUBLISHED)
   ▼
recoverStaleClaims      SENDING 超 15 分钟的回收为可重试或永久失败
enqueueLatestPublished  按订阅者时区本地时间到点，且 published_at ≥ confirmed_at，
   │                    且未投递过 → 插 email_delivery
   │                    唯一索引 (subscription_id, report_id) 保证不重发
claimDue                FOR UPDATE SKIP LOCKED 抢占，attempt_count + 1
loadDeliverable         再次校验订阅 ACTIVE + 报告 PUBLISHED，否则 SKIPPED
send                    markSent / markFailed（10min → 60min，3 次后 PERMANENT_FAILED）
```

订阅是**双确认**：`report_subscription_request`（24 小时过期、10 分钟内不重发确认信）→
确认后才写 `report_subscription`。退订令牌带 `token_version`，退订即版本 +1 让旧链接失效。
邮件只投递已发布的报告快照，**不为每个收件人重新调用模型**。

#### 线 5：管理面

`/api/v1/admin/**` 由 `AdminAuthFilter` **按路径前缀**拦截（不是按注解——注解漏标就是漏防护）：
Bearer token → `admin_principal` 解析角色 → 非 GET 需要 `canMutate()`。拒绝一律返回同一句
`{"error":"forbidden"}`，不泄露失败原因。写操作要求 `Idempotency-Key`，响应存进
`admin_idempotency`，重试不会重复产生状态变更和审计。

**web 容器持有的是 VIEWER 只读 token** —— 拿下 web 容器不等于拿下采集管道。

---

## 技术架构

### 进程拓扑（生产 10 个容器）

```text
Browser
  │ HTTPS
  ▼
caddy :80/:443 ──────────► web :3000        Next.js 15.5.23 / React 19 / TypeScript
                             │              SSR 页面、同源代理、SSE 流式问答
              ┌──────────────┴──────────────┐
              ▼                             ▼
    core-api :8080                  ai-service :8000
    Spring Boot 3.4.1 / Java 21     FastAPI / Python 3.12
    内容读 API、报告发布、订阅        RAG 检索与生成、评测、运行统计
    RBAC / 幂等 / 审计 / SMTP
              │                             │
              └──────────────┬──────────────┘
                             ▼
              postgres  PostgreSQL 16 + pgvector（唯一事实源，Flyway V027）
              redis     Redis 7（缓存、限流、短锁；可丢弃重建）

后台常驻：scheduler（采集）· pipeline（加工/报告）· monitor（告警）· backup（备份）
```

### 服务边界

| 层 | 负责 | 明确不负责 |
|---|---|---|
| Web | 页面、交互、同源代理、流式问答 UI | 直接查库、持有模型密钥或 OPERATOR 凭据 |
| Core API | 公共读 API、报告发布状态机、双确认订阅、邮件投递、RBAC / 幂等 / 审计 | 网页抽取、embedding、RAG 检索算法 |
| AI Service | 采集、正文处理、结构化、聚类、报告生成、RAG 与评测 | 用户权限、订阅事实、邮件投递状态机 |
| PostgreSQL | 内容版本、证据块、Story、报告、订阅、审计与向量 | —— 它就是事实源 |
| Redis | 查询缓存、速率限制、短锁、会话热副本 | 持久业务事实、跨服务一致性的唯一依据 |

这一列"不负责"不是免责声明，是**分工的定义**：Web 拿不到写权限，所以前端被攻破不会污染
数据；AI Service 不碰订阅状态机，所以模型侧的故障不会让邮件重复投递。

### 为什么是两种语言

按**业务边界**拆，不是按语言偏好。Java 承担稳定事务、权限和交付语义（订阅状态机、幂等键、
审计链）；Python 承担变化更快的采集、模型和评测生态（adapter、切块、检索、黄金集）。
两侧通过 OpenAPI、共享 JSON Schema 和 PostgreSQL 的事实模型协作，不互相泄露领域对象——
Python 的检索候选对象不会变成 Java 的领域实体，Java 的订阅状态也不会在 Python 侧有第二份。

### 为什么一个 PostgreSQL 兜住全部

事务、关系、全文检索（tsvector + CJK bigram）和向量检索（pgvector HNSW）在当前体量下都由
它承担，省掉了双写、索引同步和"两个库恢复到不同时间点"的问题。什么时候该拆见
[三个工程决策](#三个工程决策)。

精确版本：Next.js 15.5.23 / React 19 / TypeScript · Spring Boot 3.4.1 / Java 21 / Maven ·
FastAPI / Python 3.12 · PostgreSQL 16 + pgvector · Redis 7 ·
DeepSeek 生成 / bge-m3 嵌入 / bge-reranker-v2-m3 重排 · Docker Compose · Caddy · GHCR · GitHub Actions

---

## 数据模型：为什么分这么多层

```text
source ──► crawl_run ──► raw_document ──► content_item ──► content_revision
  │                                            │                  │
  │                                            │                  ├──► content_chunk
  │                                            │                  │     (chunk_set_id + is_active)
  │                                            │                  │      ├─ embedding vector(1024)
  │                                            │                  │      └─ search_vector tsvector
  │                                            │                  │
  │                                            ├──► item_entity / item_topic / item_vendor_relation
  │                                            └──► story ──► story_item
  │                                                    │
  └──► source_health_daily                             └──► selection_record ──► report ──► email_delivery
                                                                                     │
rag_query ──► rag_citation ──► content_chunk (FK)                          report_subscription
     └──► rag_trace                                                             （双确认）
```

每一层独立的理由都不是"规范好看"，而是**合并了就会丢一种可追溯性**：

| 分层 | 不能合并的原因 |
|---|---|
| `content_item` / `content_revision` | 正文更新不能覆盖旧证据。旧回答引用的是**那一版**正文 |
| `content_chunk.chunk_set_id` + `is_active` | 重切块要新增一套并停用旧套，不能 DELETE —— `rag_citation` 有外键，删了要么违反约束，要么让旧回答指向另一段文字 |
| `story` / `story_item` | 去重后仍保留各家来源，`independent_source_count` 才有意义 |
| `report` + 状态机 | 邮件和网页读同一份 `PUBLISHED` 快照，不在发送时重新生成 |
| `report_subscription_request` vs `report_subscription` | 双确认：未确认的请求不是订阅 |
| `admin_idempotency` | 管理写操作重试不能重复产生审计和状态变更 |

**证据链的最小可核验单元是 `content_chunk` 的物理行。** AI 摘要写在 `content_item.summary_zh`，
只用于阅读和结构化，永远不进入 RAG 证据。

---

## 代码架构

### 仓库结构

```text
AI-Hot-Radar/
├─ apps/web/src/                        Next.js（64 文件）
│  ├─ app/page.tsx                      精选首页
│  ├─ app/{items,stories,topics,vendors}/  动态、事件、主题、厂商
│  ├─ app/{reports,ask}/                报告阅读订阅、RAG 问答与 SSE 流式 UI
│  ├─ app/{eval,ops,admin}/             质量门禁、运行状态、模型配置与信源后台
│  ├─ app/api/                          同源代理：浏览器不直连后端，密钥不进浏览器
│  └─ components/ lib/                  复用组件与取数封装
│
├─ apps/core-api/src/main/java/…/coreapi/   Spring Boot（65 文件）
│  ├─ content/                          公共读 API（内容、热点、Story、主题、厂商）
│  ├─ subscription/                     双确认订阅、到期扫描、SMTP 投递、幂等记录
│  ├─ admin/                            RBAC 过滤器、审计、幂等键、报告发布、模型配置
│  ├─ cache/                            Redis 读缓存边界
│  └─ observability/ health/            运行指标与健康检查
│
├─ apps/ai-service/src/ahr/             FastAPI（87 文件）
│  ├─ ingestion/                        调度租约、7 种 adapter、SSRF、全文门、幂等写入
│  ├─ processing/                       切块、simhash 去重、LLM 结构化、Story、精选、报告
│  ├─ rag/                              计划、三路召回、融合、重排、选证、生成、引用绑定
│  ├─ rag/eval/                         90 题黄金集评测与指标汇总
│  └─ spend.py tracing.py               token 预算与链路追踪
│
├─ database/migrations/                 Flyway V001–V027，数据库可执行演进历史
├─ api/ + schemas/                      OpenAPI 与 Java/Python 共享结构契约
├─ config/                              信源注册表、采集 profile、主题词表、模型白名单
├─ data/golden/                         90 题黄金集与可复现实验输入
├─ infra/                               Compose、Caddy、部署/备份/恢复/预检脚本
└─ docs/                                规格、ADR、工程手册、运行证据（151 份）
```

### 一个用户动作走到哪些文件

```text
读者在首页看到一条动态
  config/sources.yaml → ingestion/registry.py → ingestion/scheduler.py（租约）
  → ingestion/adapters/* → ingestion/http.py + ssrf.py → article.py + fulltext_gate.py
  → ingestion/repository.py（幂等写 item/revision）
  → processing/worker.py → processing/llm.py + schemas.py（结构化）
  → chunking.py / dedup.py / story.py / selection.py
  → Core API content/* → Web app/page.tsx

读者提一个问题
  Web app/ask/ → app/api/ask/route.ts（同源代理）
  → ai-service rag/service.py:answer_question
  → rag/planner.py（+ llm_planner.py）→ rag/retrieval.py（dense/sparse/temporal）
  → rag/fusion.py → rag/rerank.py → rag/dimensions.py → rag/folding.py → rag/parent.py
  → rag/answer.py：生成 → bind_citations() 服务端绑定 → check_invariants() 四条硬断言
  → rag/support.py（cross-encoder 支持度）→ rag/safety.py（凭据输出保护）
  → 落 rag_query / rag_citation / rag_trace

读者订阅报告
  Web components/ReportSubscribe.tsx → /api/subscriptions（同源代理）
  → ReportSubscriptionController/Service → SubscriptionMailer（确认信）
  → 用户点确认 → report_subscription ACTIVE
  → ReportEmailDeliveryService（每 300 秒）→ email_delivery 幂等记录 → SMTP
```

完整逐文件说明见 [`docs/code-map.md`](docs/code-map.md)。

---

## 三个工程决策

### 一、引用是服务端约束，不是模型的承诺

模型只输出"声明 + 证据编号"，**引用由服务端重新绑定**到实际召回的 chunk 和原文 URL，再逐句
校验支持关系，弱支持的句子直接删掉。模型无法伪造一条引用，因为它根本没机会写 URL。

这条约束救过一次事故：某轮生成侧可答题误拒率从 1.28% 涨到 7.69%。最初的假设是"语料变多、
证据位竞争变激烈"——听起来很合理。抓下原始模型响应后发现完全不是：答案和引用都是完整的，
只是模型偶尔直接返回 Markdown、或把编号只写进 `claims[].evidence_ids`，解析失败的分支把正文
清空了。加了带守卫的回退分支、但不放松任何一条引用不变量，**误拒回到 0/78**。

记录在 [`docs/status/eval/m4-rag-eval-GEN-20260809.md`](docs/status/eval/m4-rag-eval-GEN-20260809.md)：
可观测性要覆盖模型的原始出口，只看业务指标会把解析 bug 误判成模型能力问题。

### 二、负结果和正结果一样留档

- **B2｜加稀疏通道反而更差**：以为加 PostgreSQL 关键词召回能全面提升专名命中，实际全局 MRR
  从 `0.7630` 掉到 `0.7480`。保留为退化记录，改用按名次的 RRF 融合而不是无条件并集。
- **B8｜42 组融合权重扫描**：接上 cross-encoder 之后，最好和最差的差距只剩 `0.0004`。
  结论是**不改生产权重**——调参没有显著收益就该停。
- **接入中转站：做完又拆掉**：想让模型配置页支持任意 OpenAI 兼容中转站。实测发现中转站之间
  没有统一路径约定，我写的按供应商推导路径的规则第一条就是错的，而且错误表现是 `200 + HTML`，
  看起来像成功。权衡后整套删除，只保留官方端点 + HTML 响应检测。记录在
  [ADR-0032](docs/adr/0032-generation-provider-credentials-are-database-backed.md)。

### 三、没有证据就不引入新组件

不用 Kafka、不用独立向量库、不上 Kubernetes——不是因为不会，是因为当前体量下它们只增加
运维面而不解决任何已观测到的问题。每条都写明了触发条件：

| 现在不做 | 什么时候必须做 |
|---|---|
| 消息队列 | 后台任务出现跨服务扇出，或轮询延迟成为瓶颈 |
| 独立向量库 | 向量规模超出单机内存，或需要独立于业务库扩缩容 |
| Kubernetes | 需要多副本、滚动发布或跨机调度 |

`outbox_event` 表已经存在但**没有消费者**，当前编排是 PostgreSQL 租约轮询
（`FOR UPDATE SKIP LOCKED` + advisory lock）。这一点写进了
[ADR-0028](docs/adr/0028-current-task-orchestration-is-database-polling.md)，而不是在架构图上
画一个不存在的箭头。

---

## 边界与取舍

- **自动支持度不等于人审**。93.4% 是自动指标，高风险的数字、主体关系和结论仍需要人看。
- **没有账号体系**。RAG 历史是全站共享的公共记录。进入私有知识库之前不提前引入账号和租户隔离。
- **邮件用 Gmail SMTP**，适合上线验证，正式投递需要自有域名 + SPF/DKIM/DMARC + 退信处理。

完整边界清单和当前运行事实见 [`docs/status/current/`](docs/status/current/)。

---

## 深入阅读

仓库里的 `docs/` 有 151 份文档，按用途分四层。**从这三个入口进最快**：

| 想了解 | 去哪 |
|---|---|
| 系统怎么工作、代码在哪里 | [`docs/handbook/`](docs/handbook/README.md) — 23 篇工程教材 |
| 为什么这样选、什么时候回滚 | [`docs/adr/`](docs/adr/README.md) — 32 条决策记录 |
| 现在线上跑的是什么 | [`docs/status/current/`](docs/status/current/README.md) — 唯一当前事实入口 |

其余：[`docs/spec/`](docs/spec/) 锁定规格 · [`docs/status/eval/`](docs/status/eval/) 逐轮评测证据 ·
[`docs/code-map.md`](docs/code-map.md) 按功能索引全部实现文件 ·
[`docs/status/current/architecture-review-20260818.md`](docs/status/current/architecture-review-20260818.md)
代码/仓库/生产机三方对齐核查 · [`docs/interview/`](docs/interview/README.md) 项目讲解与技术问答。

> 引用本仓库任何指标时请带上日期、样本量、模型版本和测量环境。历史快照不是实时承诺。

---

## 本地运行

```bash
cp .env.example .env
docker compose -f infra/compose/docker-compose.yml up -d --build
```

只看代码和跑离线测试不需要任何密钥。要完整跑通采集和 RAG，需要自己的 DeepSeek 生成 key 和
SiliconFlow 嵌入/重排 key。环境变量、Windows 命令、数据初始化和排障见
[`DEVELOPMENT.md`](DEVELOPMENT.md)，三端分层测试命令见其中的「6. 运行测试」。

# AI Hot Radar

**AI 资讯问答最大的问题不是答不出来，是答得像真的。** 这个项目让每一句回答都能点回原文，
证据不够就闭嘴——而不是补一段听起来合理的话。

[![CI](https://github.com/linruibang19-home/AI-Hot-Radar/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/linruibang19-home/AI-Hot-Radar/actions/workflows/ci.yml)
[![Release](https://github.com/linruibang19-home/AI-Hot-Radar/actions/workflows/release.yml/badge.svg)](https://github.com/linruibang19-home/AI-Hot-Radar/actions/workflows/release.yml)
![Java 21](https://img.shields.io/badge/Java-21-orange)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)
![PostgreSQL 16 + pgvector](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791)

**线上地址 → [aihotradar.online](https://aihotradar.online)** ｜ 单机 2C4G 真实运行，数据每天在长

---

## 效果展示

![精选首页：持续更新的 AI 情报、热点与推荐理由](docs/assets/screenshots/home.png)

问答里的每个 `[n]` 都绑定到具体原文段落，点击回跳原网页；证据不足的句子会被删掉：

![RAG 问答：回答中的事实可回跳到原始证据](docs/assets/screenshots/rag-answer.png)

---

## 为什么做这个

AI 的新东西散落在官方博客、GitHub Release、arXiv 和几十家媒体里，同一件事被七八家转述。
你想知道的往往不是"有哪些新闻"，而是**"这周到底发生了什么，以及我凭什么信"**。

市面上的 AI 摘要工具能回答第一个问题，但答案对不对只能靠感觉——**模型说什么就是什么**。
这个项目把"凭什么信"做成了工程约束：模型只输出声明和证据编号，**引用由服务端重新绑定**
到真实 chunk 与原文 URL，再逐句校验支持关系，撑不住的句子直接删除。模型没有机会写 URL，
也就伪造不了引用。

---

## 核心特性

**引用是服务端约束，不是模型的承诺。** 模型输出 `claims[].evidence_ids`，服务端拿编号回查
真实 chunk、重新绑定原文 URL，再用 cross-encoder 逐句打分（阈值 0.30），低于阈值的引用被
剥离并重新编号。90 题固定评测集上句级引用覆盖率 **0.9881**、段落支持达标率 **0.9344**。

**答不出来会拒答，而且不会顺着假前提编。** 黄金集里有 12 道诱导题——实体不存在
（"Qwen4-Ultra 的参数量"）、前提为假（"Anthropic 因那三起事故被罚了多少"）。
**假前提错误断言 0 / 12**，是每一轮评测都稳定复现的结果。

**三路混合检索，而且证明过每一路值得存在。** 语义向量 + 中文关键词 + 时间实体三路召回，
用 RRF 按名次融合，再经 cross-encoder 精排。Recall@20 **0.8994**。
最早用最简单的轮流取合并，实测 MRR 从 `0.7630` 掉到 `0.7480`——**多一路不等于更好**。

**负结果和正结果一样留档。** `docs/status/eval/` 里保留了三类"没有采纳"的实验：
B2 简单合并反而退化、B8 权重扫参在重排后收益只剩 `0.0004` 所以**不改生产配置**、
B13 中文分词对 RAG 端到端 ±0 但对站内搜索是 10–32 倍。

**评测方法本身也被质疑过。** 误拒率一度写成"必须为零"的硬门禁。用同一镜像、同一提示词
连跑四轮，失败题数是 **2 / 1 / 1 / 3**——它是随机量，不是回归信号。门禁因此改为阈值门禁
（≤5%），零容忍只留给"编造不存在的事实"。

---

## 快速开始

```bash
git clone https://github.com/linruibang19-home/AI-Hot-Radar.git
cd AI-Hot-Radar && cp .env.example .env
docker compose -f infra/compose/docker-compose.yml up -d --build
```

打开 http://localhost:3000 。Flyway 会在 core-api 启动时建完全部表结构。

**只读代码、跑离线测试不需要任何密钥。** 要完整跑通采集与问答，需要自己的 DeepSeek 生成
key 和 SiliconFlow 嵌入/重排 key，填进 `.env` 后：

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli sync-sources
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli ingest --limit 10
```

环境变量清单、Windows 命令与排障见 [`DEVELOPMENT.md`](DEVELOPMENT.md)。

---

## 架构设计

### 业务流程：从公开信源到可核验答案

```text
公开信源（RSS / API / HTML 列表 / GitHub / arXiv）
  │
  ▼
发现元数据 ──► 回源 canonical URL ──► 全文门（ACCEPTED / METADATA_ONLY / REJECTED）
                                          │
                                          ▼
                        content_item ──► content_revision（正文版本化，不覆盖）
                                          │
              ┌───────────────────────────┴───────────────────────────┐
              ▼                                                       ▼
   LLM 结构化（Pydantic schema 校验）                    结构感知切块 → content_chunk
   zh_title / 摘要 / 实体 / 主题 / 质量分                （chunk_set 版本化，引用绑在这里）
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

所有出口读取**同一份 PostgreSQL 已发布事实**。RSS 摘要只用于发现，不冒充正文；
AI 生成的摘要用于阅读，**永远不作为 RAG 的证据**。

### 进程拓扑（生产 10 个容器）

```text
Caddy(HTTPS) → Next.js(SSR + 同源代理)
                 ├─► Core API (Spring Boot)  读接口 / 报告发布 / 订阅 / RBAC 审计
                 └─► AI Service (FastAPI)    采集 / 加工 / Embedding / Rerank / 问答
                          │
        scheduler · pipeline · monitor · backup（同镜像不同入口）
                          ▼
              PostgreSQL 16 + pgvector（唯一事实源）   Redis（缓存 / 限流 / 短锁）
```

**为什么两种语言**：Java 承担事务型读写、订阅状态机与审计；Python 承担采集解析与模型调用，
生态在这一侧。边界是 HTTP，不共享数据库连接。

**为什么一个 PostgreSQL 兜住全部**：内容、向量、状态、发布记录同库，避免业务库与向量库
双写漂移。2.7 万分块量级下 pgvector HNSW 余量充足；检索强依赖时间与实体过滤，同库可直接
SQL 联查。规模或延迟扛不住时再拆——触发条件写在 [ADR](docs/adr/README.md) 里。

### 一次提问走过的文件

```text
app/ask/ → app/api/ask/route.ts（同源代理）
  → rag/service.py:answer_question
  → rag/planner.py → rag/retrieval.py（dense / sparse / temporal）
  → rag/fusion.py → rag/rerank.py → rag/folding.py → rag/parent.py
  → rag/answer.py：生成 → bind_citations() 服务端绑定 → check_invariants()
  → rag/support.py（cross-encoder 支持度）→ rag/safety.py（凭据输出保护）
  → 落 rag_query / rag_citation / rag_trace
```

逐文件说明见 [`docs/code-map.md`](docs/code-map.md)。

---

## 技术栈

```text
                              浏览器
                                │ HTTPS
┌───────────────────────────────▼────────────────────────────────────┐
│ Caddy 2              自动 TLS · 反向代理 · 安全响应头                │
└───────────────────────────────┬────────────────────────────────────┘
┌───────────────────────────────▼────────────────────────────────────┐
│ Next.js 15.5.25      SSR · App Router · 同源 /api 代理              │
│ React 19 · TypeScript                                              │
└─────────────┬──────────────────────────────┬───────────────────────┘
              │ 内容 / 报告 / 订阅             │ 检索 / 问答
┌─────────────▼──────────────┐  ┌────────────▼───────────────────────┐
│ Core API                   │  │ AI Service                         │
│ Java 21 · Spring Boot 3.4.1│  │ Python 3.12 · FastAPI              │
│ ────────────────────────── │  │ ────────────────────────────────── │
│ 稳定读接口 · 报告发布       │  │ 采集 adapter · 全文门 · 结构化切块   │
│ 双确认订阅 · 邮件投递       │  │ 三路召回 · RRF · 重排 · 引用绑定     │
│ RBAC · 操作审计            │  │ ─────────────────────────────────  │
│ Flyway 28 个迁移           │  │ scheduler · pipeline · monitor      │
│                            │  │ backup（同镜像，不同入口）           │
└─────────────┬──────────────┘  └────────────┬───────────────────────┘
              └───────────────┬──────────────┘
┌─────────────────────────────▼──────────────────────────────────────┐
│ PostgreSQL 16 + pgvector          唯一事实源                        │
│ 内容 · 正文版本 · 向量 · 状态机 · 发布记录 · 引用 · 审计               │
├────────────────────────────────────────────────────────────────────┤
│ Redis 7                           可重建，丢了不影响正确性            │
│ 缓存 · 限流计数 · 短锁 · 会话热副本 · 30 秒运行统计                   │
└────────────────────────────────────────────────────────────────────┘

外置模型 API（不自建推理，2C4G 单机跑不动也不必跑）
  ├─ SiliconFlow · bge-m3                 嵌入，1024 维
  ├─ SiliconFlow · bge-reranker-v2-m3     重排 + 支持度打分
  └─ DeepSeek    · v4-flash               生成，可在数据库热切换

交付链
  GitHub Actions 五路门禁 → GHCR 不可变 sha-<commit> 镜像 → Compose 拉起 → 公网 smoke
  规格校验 · Python · Java · Web · 空库迁移        回滚 = IMAGE_TAG 改回上一个
```

生产数据快照（2026-09-07，历史快照，非实时承诺）：登记信源 151 / 允许调度 139 /
运行态 ACTIVE 120，内容 5061（已结构化 4689），检索分块 27749，跨源事件 3213。
**这些数字每天都在变**，实时值见站内 [运行状态](https://aihotradar.online/ops) 页。

**测试**：Python 1062 · Java 86 · Web 109，CI 覆盖规格校验、三端单测与空库迁移。

---

## Roadmap

- **黄金集定期刷新**——固定 90 题冻结在 2026-08-03 的语料上，而现在 81.6% 的内容从未参与过
  评测。已实现从真实流量挖掘候选题的链路（并排除评测自身回放造成的污染），待人工标注。
- **检索缺一个"不合格"的概念**——各通道都是 `ORDER BY … LIMIT n`，融合按名次、加权做
  归一化，于是任何问题都会返回 10 条证据；语料里没有的时候返回的是"最不差的 10 条"。
  已开始记录 cross-encoder 的绝对分作为候选信号，样本量够了再决定要不要设门槛。
- **列表类信源抽不到发布日期**——489 条里 488 条 `published_at` 为空，检索按首见日期裁时间窗，
  旧稿会显示成"刚发布"。直接回填实测会写坏数据（同一站点所有页面抽出同一个日期），
  需要先做站点级常量判据。

---

## 深入阅读

| 想了解 | 去哪 |
|---|---|
| 系统怎么工作、代码在哪 | [`docs/handbook/`](docs/handbook/README.md) — 23 篇工程教材 |
| 为什么这样选、什么时候回滚 | [`docs/adr/`](docs/adr/README.md) — 32 条决策记录 |
| 现在线上跑的是什么 | [`docs/status/current/`](docs/status/current/README.md) — 唯一当前事实入口 |
| 逐轮评测证据（含负结果） | [`docs/status/eval/`](docs/status/eval/) |

> 引用本仓库任何指标时请带上日期、样本量、模型版本和测量环境。历史快照不是实时承诺。

---

## License

暂未声明开源许可证，默认保留所有权利。代码可自由阅读与学习；如需复用请先开 issue 说明用途。

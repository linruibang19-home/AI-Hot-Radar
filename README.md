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

这些数字每天都在变——上面这一栏是快照，实时值看站内 [运行状态](https://aihotradar.online/ops)
页，或 [`docs/status/current/production-baseline.md`](docs/status/current/production-baseline.md)。

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

## 架构

```text
                      Caddy :443
                          │
                   Next.js 15 / React 19          SSR 页面、同源代理、流式问答
                     │              │
     ┌───────────────┘              └───────────────┐
     ▼                                              ▼
Spring Boot 3.4 / Java 21                 FastAPI / Python 3.12
内容读 API、报告发布、双确认订阅            采集、正文抽取、结构化、Story 聚类
RBAC / 幂等 / 审计                         切块、嵌入、混合检索、重排、生成、评测
     │                                              │
     └──────────────────┬───────────────────────────┘
                        ▼
        PostgreSQL 16 + pgvector  ← 唯一事实源
        Redis 7                   ← 缓存、限流、短锁（可丢弃重建）

后台进程：Python Scheduler（采集）/ Pipeline（加工、报告）→ PostgreSQL
```

精确版本：Next.js 15.5.23 / React 19 / TypeScript · Spring Boot 3.4.1 / Java 21 / Maven ·
FastAPI / Python 3.12 · PostgreSQL 16 + pgvector（Flyway V027）· Redis 7 ·
DeepSeek 生成 / bge-m3 嵌入 / bge-reranker-v2-m3 重排 · Docker Compose · Caddy · GHCR · GitHub Actions

**为什么用两种语言**：Java 承担稳定事务、权限和交付语义，Python 承担变化更快的采集、模型和
评测生态。两侧通过 OpenAPI、共享 JSON Schema 和 PostgreSQL 的事实模型协作，不互相泄露领域对象。

**为什么 PostgreSQL 一个库兜住**：事务、关系、全文检索和向量检索在当前体量下都由它承担，
省掉了双写和索引同步。什么时候该拆，见下面第三条。

---

## 三个工程决策

### 一、引用是服务端约束，不是模型的承诺

模型只输出"声明 + 证据编号"，**引用由服务端重新绑定**到实际召回的 chunk 和原文 URL，再逐句
校验支持关系，弱支持的句子直接删掉。模型无法伪造一条引用，因为它根本没机会写 URL。

这条约束救过一次事故：某轮生成侧可答题误拒率从 1.28% 涨到 7.69%。最初的假设是"语料变多、
证据位竞争变激烈"——听起来很合理。抓下原始模型响应后发现完全不是：答案和引用都是完整的，
只是模型偶尔直接返回 Markdown、或把编号只写进 `claims[].evidence_ids`，解析失败的分支把正文
清空了。加了带守卫的回退分支、但不放松任何一条引用不变量，**误拒回到 0/78**。

教训写在 [`docs/status/eval/m4-rag-eval-GEN-20260809.md`](docs/status/eval/m4-rag-eval-GEN-20260809.md)：
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

仓库里的 `docs/` 有 149 份文档，按用途分四层。**从这三个入口进最快**：

| 想了解 | 去哪 |
|---|---|
| 系统怎么工作、代码在哪里 | [`docs/handbook/`](docs/handbook/README.md) — 22 篇工程教材 |
| 为什么这样选、什么时候回滚 | [`docs/adr/`](docs/adr/README.md) — 32 条决策记录 |
| 现在线上跑的是什么 | [`docs/status/current/`](docs/status/current/README.md) — 唯一当前事实入口 |

其余：[`docs/spec/`](docs/spec/) 锁定规格 · [`docs/status/eval/`](docs/status/eval/) 逐轮评测证据 ·
[`docs/code-map.md`](docs/code-map.md) 按功能索引全部实现文件 ·
[`docs/interview/`](docs/interview/README.md) 项目讲解与技术问答。

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

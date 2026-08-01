# 项目进度总览

> 更新时间：2026-08-02
> 当前阶段：**M2 进行中**（M1 已完成）
> 所有数据均来自实际运行，非估算

## 1. 里程碑完成情况

| 里程碑 | 状态 | 核心产出 |
|---|---|---|
| **M0 工程骨架** | ✅ 完成 | 三服务 + Compose + Flyway + pgvector + CI + request-ID |
| **M1 真实信源与入库** | ✅ 完成 | 7 类适配器、98 源 ACTIVE、724 条内容入库、调度器 |
| **M2 内容加工与网站** | 🟡 约 60% | 切块、去重、LLM 结构化、API、前端三页 |
| M3 Story 与热点 | ⬜ 未开始 | 事件聚类、主来源、热度算法、时间线 |
| M4 RAG MVP | ⬜ 未开始 | Embedding、混合检索、RRF、引用绑定、黄金集 |
| M5 上线与增强 | ⬜ 未开始 | 域名 HTTPS、备份监控、邮件订阅、周月报 |

## 2. 数据现状（实测）

| 指标 | 数值 |
|---|---:|
| 已入库内容 `content_item` | 724 |
| 有内容的信源 | 105 |
| ACTIVE 信源 | 98 |
| 已启用信源 | 124 / 140 |
| 已 AI 结构化 | 126 |
| 检索分块 `content_chunk` | 234 |
| 抽取实体 `entity` | 551 |
| 近似重复已标记 | 6 |
| 数据库表数 | 23 |
| 数据库体积 | 48 MB |

## 3. 信源情况

### 按 profile 分布（ACTIVE）

| profile | ACTIVE | 说明 |
|---|---:|---|
| `github_release_api` | 53 | Release body 即完整发布说明 |
| `rss_to_article` | 18 | Feed 发现 + 回源抓正文 |
| `author_feed_to_article` | 10 | 专家 Newsletter |
| `static_listing_to_article` | 8 | 列表页发现 + 回源 |
| `arxiv_feed_paper` | 7 | 论文元数据 + 摘要 |
| `docs_changelog` | 8 | 按日期标题切成独立条目 |
| `public_json_api` | 1 | Hugging Face 模型卡 |

### 关键站点接入状态

| 站点 | 状态 | 备注 |
|---|---|---|
| OpenAI（GitHub SDK/Agents） | ✅ | 官网 CDN 拦截，见 [ADR-0013](../adr/0013-openai-cdn-blocks-non-browser-clients.md) |
| Anthropic | ✅ | SDK Release + Changelog |
| Google / Gemini | ✅ | Release + API Changelog |
| Hugging Face | ✅ | Blog + Hub API 模型卡 |
| DeepSeek / Kimi / GLM / 通义 | ✅ | Changelog + 模型仓库 |
| 量子位、雷峰网 | ✅ | RSS 回源 |
| Mistral / Cohere / xAI / Together / Groq | ✅ | 列表适配器实现后启用 |
| 机器之心、36氪、智东西 | ⬜ | SPA 需浏览器渲染，属 Wave C |

### 未达 ACTIVE 的信源

| 原因 | 数量 | 处理 |
|---|---:|---|
| CDN 拦截非浏览器客户端 | 2 | 降级 metadata_only，禁止绕过 |
| feed URL 失效 | 1 | 待找替代入口 |
| 站点限流 | 1 | 退避重试 |
| 需专用适配器 / SPA | 16 | Wave C，默认关闭 |

## 4. 服务与中间件

| 组件 | 地址 | 状态 | 实现进度 |
|---|---|---|---|
| Next.js web | http://localhost:3000 | healthy | 精选首页、全部动态、详情页 |
| Spring Boot core-api | http://localhost:8080 | healthy | `/api/v1/items`、`/items/{id}`、`/stats` |
| FastAPI ai-service | http://localhost:8000 | healthy | 采集、加工、调度全部功能 |
| PostgreSQL + pgvector | localhost:5432 | healthy | 23 表，4 个 Flyway 迁移 |
| Redis | localhost:6379 | healthy | 已就绪，缓存逻辑待接入 |

**全部运行在 Docker 中**，宿主机零依赖。消息队列与对象存储按 ADR-007 与规格暂不引入（Outbox 已实现，733 条事件待消费）。

## 5. 数据库设计

```
source ──┬── source_cursor        增量游标（etag / 时间 / section hash）
         ├── crawl_run            每次运行统计与错误
         └── fulltext_attempt     全文门禁判定，可审计

raw_document          原始响应，内部审计
   └── content_item                规范化内容
         ├── content_revision      正文版本 + simhash + 质量分
         │     └── content_chunk   语义分块（含 embedding 列，待 M4 填充）
         ├── item_entity ── entity 实体关系
         └── item_topic  ── topic  主题关系

outbox_event          业务写入同事务的可靠事件
processed_event       消费幂等记录
```

**迁移历史**（全部由 Flyway 管理，禁止手工改表）：

| 版本 | 内容 |
|---|---|
| V001 | 基线：source / raw_document / content_item / story / rag 等 |
| V002 | 采集运行时：discovery_url 可空、subject 列、处理状态、fulltext_attempt |
| V003 | 信源状态机扩充 METADATA_ONLY / RATE_LIMITED |
| V004 | 内容加工：simhash、去重关系、AI 结构化列、entity / item_entity / item_topic |

## 6. 已完成任务

- [x] M0 三服务骨架与 Compose 一键启动
- [x] Gradle → Maven 切换
- [x] 140 信源注册表导入与幂等同步
- [x] 7 类采集适配器（RSS / GitHub Release / arXiv / Changelog / 列表 / 仓库活动 / 公开 API）
- [x] SSRF 防护、限流分类、条件请求、指数退避
- [x] 全文质量门禁（区分 ACCEPTED / METADATA_ONLY / REJECTED）
- [x] 内容持久化与幂等（source_id+external_id / canonical_url_hash / content_sha256）
- [x] 采集调度器（`FOR UPDATE SKIP LOCKED` + 失败退避）
- [x] 语义分块（不跨标题与代码块）
- [x] SimHash 近似重复检测
- [x] DeepSeek LLM 结构化（Pydantic 校验 + 一次修复 + 死信）
- [x] core-api 内容读接口（游标分页）
- [x] 前端三个页面（精选 / 全部动态 / 详情）
- [x] 118 个离线测试，断网可通过

## 7. 待完成任务

### M2 剩余

- [ ] 主题页与主题归一（`item_topic` 目前未写入）
- [ ] 精选算法与 `selection_record`
- [ ] 全文检索（tsvector 已有列，需接入搜索页）
- [ ] 日报生成与测试邮件
- [ ] 管理后台（信源状态、任务重跑）
- [ ] Redis 缓存接入（首页、详情）
- [ ] 剩余 598 条内容完成 AI 结构化
- [ ] Lighthouse ≥ 85 验收

### M1 遗留

- [ ] 30 个源连续运行 24 小时的正式计时（调度器已就位，需长跑）

## 8. 常用命令

```bash
docker compose -f infra/compose/docker-compose.yml up -d --build
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli ingest --limit 200
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli process --limit 100
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli schedule --interval 60
```

## 9. 风险与注意事项

| 风险 | 影响 | 应对 |
|---|---|---|
| 原始 HTML 占数据库 25 MB / 48 MB | 长期增长最快 | M5 前迁对象存储或加保留期 |
| LLM 成本随内容量线性增长 | 598 条待结构化 | 按优先级分批，低质量内容跳过 |
| 中文动态站点需浏览器渲染 | 16 个源未接入 | Wave C 专项，需 robots 复核 |
| 密钥曾出现在会话记录 | 泄露风险 | **上线前必须轮换 GitHub / DeepSeek 密钥** |

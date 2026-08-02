# 项目进度总览

> 更新时间：2026-08-02
> 当前阶段：**M1 / M2 均已完成**，M3 待开始
> 所有数据均来自实际运行，非估算

## 1. 里程碑完成情况

| 里程碑 | 状态 | 核心产出 |
|---|---|---|
| **M0 工程骨架** | ✅ 完成 | 三服务 + Compose + Flyway + pgvector + CI + request-ID |
| **M1 真实信源与入库** | ✅ 完成 | 7 类适配器、95 源 ACTIVE、718 条内容入库、调度器 |
| **M2 内容加工与网站** | ✅ 完成 | 切块、去重、LLM 结构化、主题归一、精选、全文检索、日/周/月报、邮件投递、Redis 缓存、成本追踪、前端八页 |
| M3 Story 与热点 | 🟡 部分前置 | 热度算法与热榜已实现（见下方说明）；事件聚类、主来源、时间线待做 |
| M4 RAG MVP | ⬜ 未开始 | Embedding、混合检索、RRF、引用绑定、黄金集 |
| M5 上线与增强 | ⬜ 未开始 | 域名 HTTPS、备份监控、邮件订阅 |

> **关于 M3 的部分前置**：热榜所依赖的"独立信源数"目前只能用近似重复来近似，
> 绝大多数条目因此为 1。真正的多源验证需要 M3 的 Story 聚类。现在的热榜
> **是"编辑意义上的合理排序"，不是"多源验证的事件热度"**，不应对外宣称为后者。

## 2. 数据现状（实测）

| 指标 | 数值 |
|---|---:|
| 已入库内容 `content_item` | 718 |
| 有内容的信源 | 123 |
| ACTIVE 信源 | 95 |
| 已启用信源 | 124 / 140 |
| 已 AI 结构化 | 643 |
| 检索分块 `content_chunk` | 3346 |
| 抽取实体 `entity` | 2117 |
| 主题关联 `item_topic` | 704 |
| 当前精选 `selection_record` | 87 |
| 其中含 LLM 推荐理由 | 106（含历史） |
| 已算热度的条目 | 361 |
| 已生成报告 `report` | 4（2 日报 + 1 周报 + 1 月报） |
| 近似重复已标记 | 54 |
| 数据库表数 | 27 |
| 数据库体积 | 75 MB |
| 死信 | 0 |

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

> **已修复的误判**：DNS 解析失败原本被归类为 `SSRF_BLOCKED`。该错误类型不可重试，
> 于是一次短暂的 DNS 抖动就把 10 个一手信源（OpenAI / Anthropic / Google SDK、
> arXiv、DeepSeek Changelog、Latent Space 等）**永久隔离**。解析失败意味着根本
> 没有发起连接，防护逻辑并未做出任何安全判定，应归为 `TRANSIENT`。修复后
> ACTIVE 由 87 回升至 95，隔离数由 13 降至 3。

## 4. 服务与中间件

| 组件 | 地址 | 状态 | 实现进度 |
|---|---|---|---|
| Next.js web | http://localhost:3000 | healthy | 精选、全部动态、详情、报告列表、报告详情、主题地图、主题详情、信源后台 |
| Spring Boot core-api | http://localhost:8080 | healthy | items / selected / hot / categories / topics / topics.map / reports / stats / admin.sources |
| FastAPI ai-service | http://localhost:8000 | healthy | 采集、加工、调度全部功能 |
| scheduler（采集 worker） | 无端口 | running | 每 120s 轮询到期信源，`restart: unless-stopped` |
| PostgreSQL + pgvector | localhost:5432 | healthy | 27 表，9 个 Flyway 迁移 |
| Redis | localhost:6379 | healthy | **已接入读缓存**（selected 5min / topics 10min / stats 2min） |

**全部运行在 Docker 中**，宿主机零依赖。消息队列与对象存储按 ADR-007 与规格暂不引入（Outbox 已实现）。

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
         ├── item_topic  ── topic  主题关系（归一到 taxonomy.yaml）
         ├── selection_record      精选决定 + 分项因子 + 入选理由
         └── report_item ── report  日报溯源（每条可回到原文）

llm_usage             真实 token 消耗（provider 上报，非估算）

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
| V005 | 全文检索 tsvector + trigram 索引、selection_record 精选表 |
| V006 | llm_usage 成本核算表、report 扩展列、report_item 溯源表 |
| V007 | email_delivery 投递记录（delivery_key 唯一，防重复发送） |
| V008 | entity_type 扩充为 8 类，与 taxonomy.yaml 对齐（ADR-0014） |
| V009 | 推荐理由版本/模型列、hot_score 热度列、report 周期放宽为日/周/月、topic 展示元数据 |

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
- [x] 主题归一（受控词表 + 别名字典，未命中即丢弃）
- [x] 精选算法（5 因子加权 + 每日配额 + 单源上限 + 入选理由）
- [x] 全文检索（tsvector 加权 + trigram 兜底版本号）
- [x] 主题页与主题详情页
- [x] 信源后台只读页（失败源排前）
- [x] 日报生成（按类别分章 + LLM 总述 + 全条目溯源）
- [x] Redis 读缓存（实测 warm 比 cold 快约 28%）
- [x] LLM 成本追踪（provider 真实 token，非字符估算）
- [x] 加工成本控制（正文 < 200 字符跳过，不浪费调用）
- [x] 日报列表页与详情页
- [x] 日报邮件投递（HTML + 纯文本双格式、delivery_key 防重发、标题转义）
- [x] 前端 SEO 与无障碍（og/canonical/theme-color、skip link、focus ring、per-page title、robots.txt、sitemap.xml）
- [x] **LLM 逐条推荐理由**（读全文后生成，强制指出一处局限；替换掉原先千篇一律的模板拼接）
- [x] **热度算法与当前热点榜**（类型权重改为乘数、指数衰减、独立信源对数饱和）
- [x] **周报 / 月报**（与日报共用渲染与溯源路径，prompt 分别强调趋势与格局）
- [x] **分类 tab**（全部 / 模型 / 产品 / 行业 / 论文 / 教程 / 观点，一个 tab 可映射多个 content_type）
- [x] **精选排序切换**（按精选日 / 按发布时间 / 按热度，全部为可分享的 URL）
- [x] **主题地图**（四条主线分组 + 中文名 + 一句话说明，全部由 taxonomy.yaml 驱动）
- [x] 250 个测试（Python 215 + Java 22 + Web 12 + 类型检查），Python 部分断网可通过

## 7. 待完成任务

### M2 剩余

- [x] Lighthouse ≥ 85 验收 —— 四个关键页面全部达标
- [x] AI 结构化 —— 643 条完成，81 条薄内容跳过，0 死信
- [ ] 后台任务重跑（需先有鉴权，见下）

**Lighthouse 实测**（Docker headless Chrome）：

| 页面 | Performance | Accessibility | SEO |
|---|---:|---:|---:|
| 精选首页 | 96 | 100 | 100 |
| 全部动态 | 96 | 98 | 100 |
| AI 日报 | 99 | 98 | 91 |
| 主题 | 99 | 100 | 91 |

Best Practices 本地为 78，失分项**全部是 HTTPS 相关**（`Does not use HTTPS`、
`Does not redirect HTTP traffic to HTTPS`），属 M5 域名与 TLS 工作，非代码缺陷。
`docs/spec/01` §6 的验收口径是 Performance / Accessibility / SEO ≥ 85，均已达标。

> **邮件投递已实现但未配置真实 SMTP**。`.env` 里 `SMTP_HOST`/`EMAIL_FROM` 为空时命令返回
> `not_configured` 而非报错。发送链路已用本地 SMTP sink 实测：25KB 邮件，HTML 与纯文本
> 双部分各含 12 条原文链接，中文正常。

> 信源后台目前是**只读**。`AHR-QSO-700` §3 要求管理操作具备最小权限 RBAC 与二次确认，
> 而鉴权属于 M5；在此之前提供启停/重跑接口会造成无鉴权的写入面，因此推迟。

### M1 遗留

- [x] 调度器已作为常驻 Compose 服务运行（`scheduler`），24 小时计时进行中

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
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli select --days 7
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli report --period daily
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli report --period weekly
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli report --period monthly
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli reasons --limit 40
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli heat
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli seed-topics
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli send-report --date 2026-08-01 --to you@example.com
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli usage --days 30
```

```bash
docker compose -f infra/compose/docker-compose.yml exec ai-service python -m ahr.cli schedule --interval 60
```

## 9. 风险与注意事项

| 风险 | 影响 | 应对 |
|---|---|---|
| 原始 HTML 占数据库约一半体积 | 长期增长最快 | M5 前迁对象存储或加保留期 |
| LLM 成本随内容量线性增长 | 已消耗见 `ahr.cli usage` | 已加正文长度门槛跳过薄内容；按优先级分批 |
| 中文动态站点需浏览器渲染 | 16 个源未接入 | Wave C 专项，需 robots 复核 |
| 密钥曾出现在会话记录 | 泄露风险 | **上线前必须轮换 GitHub / DeepSeek 密钥** |
| 热榜的"独立信源数"绝大多数为 1 | 热度只是编辑权重的代理指标 | M3 Story 聚类后才是真实的多源验证信号；对外描述不得夸大 |
| LLM 推荐理由与摘要可能出错 | 事实性风险 | 页面已标注"AI 生成"，每条均链接原文；理由 prompt 强制指出局限 |
| `mypy>=1.13.0` 无上界 | 类型检查结果取决于安装时间 | 见待办：固定版本 |
| ~~entity_type 规格冲突~~ | 已解决 | 见 [ADR-0014](../adr/0014-entity-types-align-to-taxonomy.md)，扩充为 8 类 |
| ~~DNS 失败被判为 SSRF~~ | 已解决 | 改判 `TRANSIENT`，10 个一手信源恢复 |

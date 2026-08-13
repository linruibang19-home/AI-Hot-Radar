# 02｜采集、全文门与数据模型
## 从配置到调度

`config/sources.yaml` 登记 140 个入口，`ingestion-profiles.yaml` 描述 9 类通用适配器契约，
`site-overrides.yaml` 只保存少量站点差异。URL、优先级和抓取周期不硬编码在业务代码里。

Scheduler 查找 `next_poll_at <= now()` 的有效信源，以 `source_id` 领取有期限租约并创建
`crawl_run/ingestion_task`。同一信源不会被两个副本同时正常处理；租约过期后可安全重领。

## 发现不等于正文

```text
RSS/API/列表/站点地图发现 URL
  → canonical 规范化
  → HTTP 回源正文
  → JSON-LD / Trafilatura / Readability / selector
  → 必要且已 allowlist 时浏览器渲染
  → 全文质量门
```

RSS 摘要、搜索 snippet 和列表描述是 discovery metadata，不是最终语料。全文门检查正文长度、
正文/摘要比例、占位页、登录墙、重复导航和访问政策；未通过时保留原因与可重放 fixture，
不能把摘要“升级”为全文。

## 外部调用防线

- 仅允许 `http/https`，DNS/IP 与每次重定向都重新做 SSRF 检查；
- 禁止环回、私网和 metadata 地址；限制响应大小、解压比与处理时间；
- connect/read timeout、有限重试、指数退避与 jitter；
- per-host 并发与速率限制，支持 ETag/Last-Modified/304；
- 每次运行保存 trace、尝试、错误码和下次重试时间。

## 幂等与版本

URL 先统一 host、默认端口、路径、fragment、追踪参数和页面 canonical，再计算 `url_hash`。
`source_id + external_id`、canonical URL、内容 hash 与数据库唯一键共同防重。正文变化生成新的
`content_revision`，处理任务绑定 revision/input hash；晚到旧结果只能记录 `STALE_RESULT`，
不能覆盖新正文。

必须区分：

1. 完全重复文章；
2. 近似转载；
3. 多篇独立内容描述同一事件。

前两者影响内容压缩，第三者进入同一 Story 但仍保留来源独立性。

## LLM 结构化与切块

DeepSeek 读取不可信正文，返回受 Pydantic/JSON Schema 约束的中文摘要、内容类型、实体、主题、
claims、事件动作/对象/时间和质量因子。解析失败最多修复一次，仍失败进入可重试或死信状态；
自由文本不能直接作为数据库结构。

切块遵循标题与语义边界：目标 250–500 tokens、最大 700、重叠 40–80，不跨标题、列表、
代码块和引用。每块保留 `heading_path`、字符位置、发布时间、语言、token 和引用资格；bge-m3
为可引用块生成向量，PostgreSQL 同时构建全文索引。

这里必须能回答“切的是原文还是摘要”：`chunk_current_revisions()` 从
`content_item.current_revision_id → content_revision.body_text` 读取当前 canonical 正文，
`chunk_revision()` 把切分结果逐条写入 `content_chunk.body_text`。`summary_zh` 不参与这条路径。
Embedding 前会临时在 passage 前加标题、来源、日期和最多三层 heading，解决孤立 changelog bullet
缺少语境的问题；这个前缀**只进入向量模型输入，不回写 chunk，也不能作为引用正文**。

当前实现参数是 target 400、min 120、max 700、overlap 60、异常结构硬上限 1200 token。普通正文按
段落、列表、标题和代码围栏切分；长表格按行切；没有换行的异常长行再按 token 预算和临近标点切。
切块保存 ordinal、heading path、char_start/char_end，revision 更新后只检索 current revision，旧版本
保留审计但不会混入在线答案。上线实测口径与 SQL 见
[`../status/rag-corpus-audit-20260813.md`](../status/product/rag-corpus-audit-20260813.md)。

## 核心实体

| 实体 | 作用 | 一致性要点 |
|---|---|---|
| `source` / `source_cursor` / `crawl_run` | 配置、游标、一次运行 | 状态来自调度事实，不靠前端手填 |
| `raw_document` | 原始响应元数据与输入 hash | 内部审计，不直接公开 |
| `content_item` / `content_revision` | 稳定身份与版本化正文 | 更新不覆盖旧处理版本 |
| `content_chunk` | 逻辑 evidence passage 的物理行 | 保存定位、向量、全文字段和模型版本 |
| `entity` / `content_entity` / `topic` | 公司、模型、技术与关系 | 别名先归一，低置信度不盲建实体 |
| `story` / `story_item` | 跨来源事件聚合 | 人工锁定后自动聚类不能覆盖 |
| `selection_record` / `report` | 精选决定与发布快照 | 发布与投递读取已保存事实 |
| `rag_query` / `rag_citation` | 计划、候选、回答与绑定 | 每次问答可重放、可解释 |
| `report_subscription` / delivery | 订阅和投递事实 | 双确认、时区、唯一键、退订 |

## Story 聚类

候选首先受时间窗口约束，再综合标题/摘要语义、实体重叠、动作对象、引用链接、时间距离与主题。
同一公司不同模型版本不能只因实体相同合并；官方发布与媒体评测可以在同一 Story 中扮演不同角色；
更正必须保留方向。主来源优先级是一手官方 > 官方文档/仓库 > 论文 > 权威媒体 > 技术作者 > 聚合。

## 状态机与失败隔离

```text
DISCOVERED → FETCHED → PARSED → NORMALIZED → ENRICHED → READY
                 ↘ FETCH_FAILED / ACCESS_RESTRICTED
                           ↘ PARSE_FAILED / FULLTEXT_REJECTED
```

一次信源失败只影响该 source 的失败阶梯；历史已发布内容继续服务。状态转移写尝试次数、错误码、
下次重试和处理器版本。信源后台展示 PostgreSQL 最新快照，刷新页面才重新读取，不是秒级监控。

## 数据政策

付费墙、登录内容和禁止存储的页面只保存元数据、短摘要与原文链接；公共页面默认不镜像全文。
RAG 只检索已发布且可引用的原始 passage。下架时公共正文、向量与缓存一并移除，只保留最小审计事实。

## 面试官要求看 SQL 时

先打开 `database/migrations/V001__baseline.sql` 讲 source/raw/item/revision/chunk，再按功能迁移讲
Story、RAG、报告订阅和模型配置。明确 `evidence_passage`、`embedding_record` 是早期领域名，
当前没有这两张物理表；引用和向量都在 `content_chunk`，见 ADR-0029。

## 面试官继续追问“如何证明不是摘要”

按四层证据回答，不只说“代码看起来如此”：

1. 迁移层：`content_revision.body_text`、`content_item.summary_zh` 和 `content_chunk.body_text` 是不同列；
2. 写入层：`pipeline.py::chunk_revision` 的唯一文本输入是 revision body；
3. 向量层：`rag/backfill.py` 读取 chunk body，`rag/context.py` 明确上下文前缀仅用于 embedding；
4. 生产层：抽查 chunk 与 revision 定位、模型覆盖、空块、摘要相等数量和超限块，并保存带日期的审计。

不要回答“100% 永远正确”。本次审计发现并修复了 14 个旧版超长单行块，说明门禁的价值正是让
反例暴露出来；部署后通过定向 rechunk 和重向量化收口，而不是删数据或口头忽略。

# OpenAI 官网资讯入库与列表发布日期（2026-09-28）

> 生产数字来自 09-28 对 `47.243.15.6` 的只读查询；本地验证在本机 Docker（PostgreSQL V027）上完成。
> 决策见 [ADR-0013 落地补记](../../adr/0013-openai-cdn-blocks-non-browser-clients.md#落地2026-09-28-补记)。

## 1. 起因

一次「截图里的信源都具备了吗」的核查，把两个已知但一直没修的缺口摆到了一起：

| 缺口 | 生产证据（09-28） | 影响 |
|---|---|---|
| OpenAI 官网资讯 0 条 | `openai-news` 每轮发现 154 条、抓取 0 条，状态 `PROBING`；文章页从香港出口一律 403；`/health/sources` 停滞告警连续 5,466 次 | 做 AI 资讯的站点，OpenAI 官方动态只能来自媒体转述 |
| 列表源没有发布日期 | 7,905 条中 1,136 条 `published_at` 为空；`anthropic-news` 14 条全空 | 检索按 `COALESCE(published_at, observed_at)` 裁时间窗，旧稿显示成「首次抓到那天发布」 |

第一条在 2026-08-01 的 ADR-0013 里已经有决策（保留元数据），但配置没改、代码没有对应分支——
决策停在了文档里。第二条在 09-22 审计里记为已知缺口，当时的结论是「宁可留空，不写错日期」。

## 2. 改了什么

**被拒时保留发现记录**（`ingestion/pipeline.py`、`ingestion/models.py`）

- 仅对 `content_access: metadata_abstract` 的信源生效；`openai-news` 改为此值。
- 文章页 401/403 → 写一条 `METADATA_ONLY`：空正文、feed 简介存 `discovery_summary`、
  `extraction_method = discovery_metadata`、`reason_code = ARTICLE_ACCESS_RESTRICTED`、`http_status = 403`。
- 写入即推进游标：以前被拒的同 5 篇每轮都会被重新请求一次，现在每篇只问一次。
- 全文信源的 403 不变，仍是失败——对它们而言被拒是故障，不是可以存下来的形态。

**只展示、不引用**（`processing/pipeline.py`、`processing/llm.py`）

- 处理阶段识别 `discovery_metadata`：不做 simhash 近重复（一句话太短，指纹没有意义），不受
  200 字富化门槛限制，用简介富化；提示词写明「未取得正文，只复述简介，1–2 句」。
- `attributes.enrichment_basis` 记录摘要依据的是正文还是简介。
- 切块查询仍要求 `length(body_text) > 0`，这类内容**没有分块，不可能进入 RAG 证据**。

**列表卡片日期**（`ingestion/adapters/listing.py`、`ingestion/repository.py`、`cli.py`）

- 列表链接里恰好印着**一个**日期时，作为 `published_at`；两个不同日期（比如卡片还提到活动日期）
  视为无法判断，留空。只识别 `Sep 23, 2026`、`23 Sep 2026`、`2026-09-23`、`2026年9月23日` 四种写法，
  月份名要求完整单词（`Mayor 3, 2026` 不算）。日期只有年月日时取当天 00:00 UTC，与 changelog 适配器一致。
- 同一文章常有图片链接和标题链接两个 `<a>`，日期只在其中一个里：先在全部链接上取日期，再截窗口。
- `ahr backfill-listing-dates [--source] [--dry-run]`：读一次各列表页，**只填空值**，已有日期一律不动。

## 3. 验证

**列表日期——生产同款页面离线评估**（09-28 从生产主机抓取 18 个已启用列表页）：

| 信源 | 链接数 | 取到日期 |
|---|---:|---:|
| anthropic-news | 11 | 10 |
| cerebras-blog | 49 | 48 |
| groq-blog | 14 | 14 |
| cohere-blog | 57 | 22 |
| huggingface-blog | 57 | 16 |
| 其余 11 个（meta、together、stability、elevenlabs 等） | — | 0 |

逐条抽查四个有日期的站（各 7 条），日期均为发布日期。取不到日期的站保持原样——这是覆盖率问题，不是错误。

**OpenAI——本地真实数据库**：`sync-sources` 后用生产同款 RSS（1,230 条）+ 模拟文章页 403 跑 `ingest_source`：

- 5 条入库，`METADATA_ONLY / ARTICLE_ACCESS_RESTRICTED`，`raw_document.http_status = 403`，信源状态 `METADATA_ONLY`，0 条错误；
- 处理阶段真实调用 DeepSeek 富化 5 条（2,905 prompt / 908 completion token）：摘要是简介的忠实中译，
  没有补充内容；5 条全部通过公开列表门槛，分块数 0；
- 浏览器：列表页按发布日期分组显示，详情页有中文标题、AI 摘要、发布时间与「阅读原文」。

**测试**：新增 `test_discovery_metadata.py`（10）与 `test_listing_card_dates.py`（10）；
Python 全量 1142 passed；`ruff check`、`ruff format --check`、`mypy src` 通过。

## 4. 没做的与仍然存在的

- **OpenAI 正文仍拿不到**。这是 CDN 对非浏览器客户端的防护，ADR-0013 明确不绕过；OpenAI 相关的 RAG 回答
  仍只能引用媒体报道与官方 SDK / 状态页。
- **xAI 仍是 0**：`xai-news` 的列表页本身 403，连发现都做不到，本次改动帮不上。
- 列表日期只覆盖卡片里印着日期的站；Meta、Together 等仍无日期。已被挤出列表页的旧条目，回填也找不到。
- 3 个 OpenAI 文档 changelog 仍被隔离（`docs_changelog` 没有「发现」与「正文」之分，整页被拒）。

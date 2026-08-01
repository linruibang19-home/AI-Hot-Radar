# 03｜数据模型、采集与事件流水线

文档 ID：`AHR-DATA-300`

## 1. 核心实体

| 表 | 主键 | 用途 |
|---|---|---|
| `source` | UUID | 信源配置、权威度、抓取政策 |
| `source_cursor` | source_id | ETag、Last-Modified、游标和上次成功时间 |
| `crawl_run` | UUID | 一次信源运行及统计 |
| `raw_document` | UUID | 原始响应元数据、对象引用、输入 hash |
| `content_item` | UUID | 单篇标准化资讯 |
| `content_revision` | UUID | 标题、正文和结构化字段版本 |
| `evidence_passage` | UUID | 可引用证据段及定位信息 |
| `entity` | UUID | 公司、产品、模型、技术、人物 |
| `item_entity` | item_id+entity_id | 提及、主语/宾语、置信度 |
| `topic` | UUID | 稳定主题体系 |
| `item_topic` | item_id+topic_id | 分类与置信度 |
| `story` | UUID | 真实事件聚合单元 |
| `story_item` | story_id+item_id | 支持、主来源、纠正或观点关系 |
| `story_relation` | from+to+type | 前因、后续、竞争、纠正等 Graph-lite 边 |
| `embedding_record` | UUID | item/story/passage 向量和模型版本 |
| `selection_record` | UUID | 精选决定、分数和理由 |
| `report` | UUID | 日/周/月报及版本 |
| `report_story` | report_id+story_id | 报告章节、顺序和角色 |
| `rag_query` | UUID | 解析计划、耗时和评测标签 |
| `rag_citation` | UUID | 答案主张到 passage 的绑定 |
| `outbox_event` | UUID | 可靠任务事件 |
| `audit_log` | UUID | 人工和系统关键变更审计 |

## 2. 必须字段

`content_item` 至少包含：

```text
id, source_id, external_id, canonical_url, url_hash,
original_title, zh_title, language, author,
published_at, updated_at, fetched_at,
content_hash, clean_text, summary,
content_type, source_tier, quality_score,
status, processor_version, created_at
```

`evidence_passage` 至少包含：

```text
id, item_id, revision_id, passage_index,
heading_path, text, text_hash,
char_start, char_end, source_locator,
published_at, language, token_count,
is_quote_eligible, created_at
```

`story` 至少包含：

```text
id, slug, title, digest, status,
event_started_at, first_report_at, latest_report_at,
primary_item_id, independent_source_count,
quality_score, hot_score, clustering_version,
human_locked, created_at, updated_at
```

## 3. 索引

- `content_item(canonical_url)` 唯一；
- `content_item(source_id, external_id)` 条件唯一；
- `content_item(published_at desc, status, content_type)`；
- `item_entity(entity_id, item_id)`；
- `story(latest_report_at desc, status)`；
- `evidence_passage(item_id, passage_index)`；
- `tsvector`：标题 A、实体别名 A、摘要 B、正文 C；
- pgvector HNSW 索引按实际维度创建；小于 50k 向量时先评估顺序扫描；
- 向量查询必须先尽可能执行时间、语言、状态等过滤。

## 4. 采集适配器

统一接口：

```python
class SourceAdapter(Protocol):
    async def discover(self, source, cursor) -> list[DiscoveredRef]: ...
    async def fetch(self, ref) -> RawPayload: ...
    async def checkpoint(self) -> SourceCheckpoint: ...
```

第一批实现顺序：

1. `RssAtomDiscoveryAdapter`：只负责发现 entry，若 feed 不是全文必须继续回源；
2. `DocsChangelogAdapter`：按标题层级和内容 hash 生成 revision；
3. `GitHubReleasesApiAdapter`：REST API 优先，Atom 降级，保存完整 release body；
4. `GitHubRepoActivityAdapter`：只监控重要 tag、release、README/CHANGELOG 变化；
5. `HtmlListingAdapter` / `SitemapAdapter`：发现 canonical 文章 URL；
6. `ArticleFulltextAdapter`：JSON-LD → Trafilatura → Readability → selector；
7. `ArxivPaperAdapter`：RSS 发现、HTML/PDF 正文解析；
8. `PublicJsonApiAdapter`：Hugging Face/OpenAlex 等带 cursor 或时间戳的公开 API；
9. `BrowserRenderedAdapter`：默认禁用，仅 allowlist 且 HTTP 抽取失败后使用；
10. `AuthorizedSocialAdapter`：只有授权接口配置后才可启用。

`config/sources.yaml` 是可采集信源事实配置，`config/social-watchlist.yaml` 是受限监控配置；代码不得硬编码具体站点 URL、优先级和抓取间隔。完整门禁见 `09-source-registry-fulltext.md`。

## 5. URL 与重复处理

规范化顺序：

```text
解析 URL -> 小写 host -> 去默认端口 -> 规范 path
-> 删除 fragment -> 删除 utm/ref 等跟踪参数
-> 站点级 canonical 规则 -> 读取页面 canonical
-> 计算 url_hash
```

重复判断分三层：

1. **完全重复**：相同 external ID、canonical URL 或正文 hash；
2. **近似转载**：SimHash/MinHash + 标题/正文相似度；
3. **同一事件**：实体、时间、动作和语义相似，但文章可保留为独立来源。

不得把“文章重复”与“事件相同”混为一谈。

## 6. 正文抽取与切块

RSS/列表页仅负责发现；当 profile 标记 `requires_article_fetch=true` 时必须继续请求 canonical 文章页。网页正文优先 JSON-LD/Trafilatura/readability；保留标题层级、链接、代码块和图片引用。正文质量低于阈值时启用站点 selector，再考虑 allowlist 内的 Playwright。禁止把搜索摘要或 RSS 摘要伪装为全文。

AI Hot Radar 使用语义/结构切块，不采用固定字符盲切：

- 单段目标 250–500 tokens；
- 最大 700 tokens，重叠 40–80 tokens；
- 不跨标题、列表、代码块和引用边界；
- 每块保存 `heading_path` 和字符定位；
- 过短相邻段合并；
- 同时生成 80–150 tokens 的 item 检索摘要；
- Story 生成独立的事件摘要索引，但不得作为唯一引用证据。

## 7. AI 结构化契约

LLM 返回必须符合：

```json
{
  "summary_zh": "string",
  "content_type": "model_release|product_release|api_update|research|open_source|business|policy|security|opinion|tutorial",
  "entities": [{"name":"string","type":"company|product|model|technology|person","role":"subject|object|mention","confidence":0.0}],
  "topics": [{"slug":"string","confidence":0.0}],
  "claims": [{"text":"string","passage_indexes":[0],"confidence":0.0}],
  "event": {"action":"string","object":"string","event_time":"ISO-8601|null"},
  "quality_factors": {"relevance":0,"information_gain":0,"technical_depth":0,"spam_penalty":0}
}
```

实体先经过 alias 字典归一，再允许创建候选实体；低置信度实体进入人工队列。

## 8. Story 聚类

候选窗口默认：发布时间前后 72 小时；长期事件可以按实体/主题扩大到 30 天。聚类特征：

```text
0.35 * title_and_summary_embedding
+ 0.25 * entity_overlap
+ 0.15 * action_object_match
+ 0.10 * url_or_quote_link
+ 0.10 * time_proximity
+ 0.05 * topic_overlap
```

硬规则：

- 不同模型版本不得仅因公司相同合并；
- 官方“发布”与后续媒体“评测”可以同 Story，但关系角色不同；
- 更正/撤回必须关联原 Story 并保留方向；
- 高风险自动合并先进入 `cluster_suggestion`；
- 人工锁定 Story 不自动拆并。

主来源选择：官方当事方 > 官方文档/仓库 > 论文 > 权威媒体 > 技术作者 > 聚合转载。若主来源不覆盖最新变化，Story 摘要必须同时引用补充来源。

## 9. 数据保留与版权

- RSS 只含摘要时，不尝试伪造全文；
- 付费墙、登录内容、公众号和明确禁止存储的页面仅保存元数据、短摘要和原文链接；
- 原始 HTML 的保留期与用途按 `content_policy` 执行；
- 用户可通过 URL/权利人信息提交下架；下架后公共正文、向量和缓存一并删除，保留最小审计记录；
- RAG 只能检索 `status=PUBLISHED` 且 `is_quote_eligible=true` 的 passage。

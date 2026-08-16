# 10｜信源接口读取与 Adapter 实现

文档 ID：`AHR-INGEST-1000`  
版本：`v1.2.0`  
状态：开发基线

## 1. 先澄清：“信源接口”不全是 API

AI Hot Radar 面对的公开信源分成五种读取方式：

| 类型 | 如何发现新内容 | 怎样取得正文 | 典型来源 |
|---|---|---|---|
| RSS/Atom | GET Feed，读取 entry | 再 GET `entry.link` 并抽取正文 | OpenAI News、博客、Newsletter |
| 官方 JSON API | GET API，按 cursor/page 翻页 | API 字段本身或继续读取 canonical 文档 | GitHub、Hugging Face、OpenAlex |
| 更新日志 | GET 固定页面，比对 ETag/正文 hash | 按日期/版本标题切成独立 revision | API Changelog、Release Notes |
| HTML/Sitemap | 从 Sitemap、JSON-LD、列表页发现 URL | GET 文章页，抽取 `article/main` | Anthropic、DeepMind、国内媒体 |
| 动态/受限平台 | 合规公开接口或浏览器渲染 | 原文外链优先；无授权则只做线索 | X、公众号、部分动态站点 |

因此系统不是“调用一个新闻 API 就得到所有全文”，而是统一实现：

```text
Source 配置 → Adapter 发现候选 → DocumentFetcher 回源 → Extractor 抽正文
→ FulltextGate 验证 → Normalizer 统一字段 → 入库/outbox
```

## 2. 模块边界

Python Worker 定义以下协议；所有 Adapter 输出同一个 `DiscoveredDocument`，下游不关心来源类型。

```python
class SourceAdapter(Protocol):
    async def discover(self, source: SourceConfig, cursor: SourceCursor) -> DiscoveryBatch: ...

class DocumentFetcher(Protocol):
    async def fetch(self, request: FetchRequest) -> RawResponse: ...

class ContentExtractor(Protocol):
    async def extract(self, raw: RawResponse, rules: ExtractionRules) -> ExtractedDocument: ...

class FulltextGate(Protocol):
    def evaluate(self, document: ExtractedDocument) -> QualityDecision: ...
```

当前实现中，Python Scheduler 负责 Source 轮询和租约，Python Pipeline 负责网络采集、
HTML/PDF/Markdown 解析、正文质量、内容加工、Embedding、聚类、精选、报告和 RAG。
Java Core API 负责公开内容/报告读取、订阅邮件、管理状态与审计。两者共享 PostgreSQL
事实源；当前使用 task/state 表、`FOR UPDATE SKIP LOCKED` 和 advisory lock，不存在 Outbox
消费者。RabbitMQ 只在压测证明需要时评估，见 ADR-0028。

## 3. RSS/Atom：Feed 只发现，文章页才是正文

请求：

```http
GET /news/rss.xml HTTP/1.1
Host: openai.com
User-Agent: AIHotRadarBot/1.0 (+https://example.com/bot)
Accept: application/rss+xml, application/atom+xml, application/xml, text/xml
If-None-Match: "previous-etag"
If-Modified-Since: Wed, 29 Jul 2026 10:00:00 GMT
```

处理步骤：

1. 304：更新 `last_checked_at`，不创建内容；
2. 200：保存原始 Feed 响应、ETag、Last-Modified；
3. 用 feedparser 读取 `id/guid/link/title/published/updated/summary`；
4. `external_id = guid ?? id ?? sha256(canonicalized_link)`；
5. 未见过的条目创建 `DOCUMENT_FETCH_REQUESTED`；
6. 再请求文章 URL，跟随最多 5 次跳转；
7. 从 `rel=canonical`、OpenGraph、最终 URL 决定 canonical；
8. JSON-LD → Trafilatura → Readability → selector 依次抽取；
9. Feed summary 仅保存为 `discovery_summary`，永不写入 `body_text`。

伪代码：

```python
async def discover_rss(source, cursor):
    response = await http.get(source.discovery_url, headers=conditional(cursor))
    if response.status_code == 304:
        return DiscoveryBatch.not_modified(response.headers)
    feed = feedparser.loads(response.body)
    items = []
    for entry in feed.entries:
        url = canonicalize_url(entry.link)
        external_id = entry.get("id") or sha256(url)
        if not await seen(source.id, external_id):
            items.append(DiscoveredDocument(
                external_id=external_id,
                candidate_url=url,
                title_hint=entry.get("title"),
                published_at_hint=parse_feed_time(entry),
                discovery_summary=entry.get("summary"),
                requires_fetch=True,
            ))
    return DiscoveryBatch(items=items, next_cursor=cursor_from(response, feed))
```

## 4. GitHub Releases API：API body 就是完整发布说明

官方端点为 `GET /repos/{owner}/{repo}/releases`。公开仓库可匿名读取，但生产环境应配置只读 Token 以提高限额。官方文档说明列表不包含“只有 Tag、没有 Release”的普通标签，因此 Tag 需要单独降级处理。

```http
GET /repos/langchain-ai/langgraph/releases?per_page=100&page=1 HTTP/1.1
Host: api.github.com
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2026-03-10
Authorization: Bearer ${GITHUB_TOKEN}
If-None-Match: "previous-etag"
```

字段映射：

| GitHub 字段 | 系统字段 |
|---|---|
| `id` | `external_id` |
| `html_url` | `canonical_url` |
| `name ?? tag_name` | `title` |
| `body` | `body_markdown` 与 `body_text` |
| `published_at` | `published_at` |
| `draft` | draft=true 时忽略 |
| `prerelease` | `content_attributes.prerelease` |

分页读取 `Link` 响应头；达到已知 `max_release_id/max_published_at` 后停止。保存 `X-RateLimit-Remaining/Reset`，低水位时暂停该 Host。Release body 为空时可保留元数据，但不能计为全文成功。

参考：[GitHub Releases REST API](https://docs.github.com/en/rest/releases/releases)。

## 5. 官方更新日志：固定 URL 的增量 diff

更新日志通常没有“每条独立 API”。读取方式是对固定页面做条件请求并生成 revision：

```text
GET 页面 → 提取 main → 转 Markdown → 按日期/版本 heading 切分
→ 对每个 section 算 sha256 → 新 hash 新增，旧 identity 新 hash 更新
```

必须同时保存：

- 页面级 `raw_document`；
- section 级 `content_item`；
- `page_hash` 与 `section_hash`；
- section 的 heading、anchor、observed_at；
- 如果页面不提供发布日期，使用 heading 日期；仍没有则 `published_at=null`、`observed_at` 单独记录，禁止伪造发布日期。

## 6. HTML/Sitemap：从列表发现，再回源文章

通用发现优先级：

1. Sitemap `<loc>` 与 `<lastmod>`；
2. JSON-LD `ItemList/BlogPosting/NewsArticle`；
3. 列表页内同站文章链接；
4. 站点声明式 selector；
5. 只有策略审核通过才使用 Playwright。

Sitemap 实现还必须满足以下约束：

- XML 实体先解码，`<lastmod>` 仅用于候选排序，不能冒充文章发布日期；
- 每轮只保留 `max_documents` 个最新候选，启用新来源时不隐式回填数千条历史 URL；
- 只有正文抓取、质量门禁与持久化都成功的 URL 才写入游标 `seen`；失败 URL 留待下一轮重试；
- Sitemap 通常不含文章标题，最终标题取文章页 metadata/HTML `<title>`，不能把站点名或 URL 当标题；
- 每个站点都要有 Sitemap 与文章页两类离线 fixture，测试发现、正文、标题和游标语义。

正文提取优先级：

```text
JSON-LD articleBody
→ Trafilatura
→ Mozilla Readability
→ config/site-overrides.yaml selector
→ Playwright 渲染后的同一抽取链
```

Playwright 不是绕过工具。出现登录墙、验证码、付费墙或访问拒绝时记录 `ACCESS_RESTRICTED`，降级为元数据/链接，不回放 Cookie、不绕验证码。

## 7. Hugging Face：API 发现模型，README 是模型卡正文

```text
GET https://huggingface.co/api/models?... 发现模型
→ 读取 id、lastModified、tags
→ GET https://huggingface.co/{id}/raw/main/README.md
→ 保存原始 Markdown、front matter、正文与 canonical 模型页
```

不是每个模型变更都算新闻。至少命中以下条件之一才入候选：一手组织、近期显著更新、配置中的关注实体、热度阈值或与已知 Story 相关。模型卡不存在时只存元数据。

参考：[Hugging Face Hub API](https://huggingface.co/docs/hub/api)。

## 8. arXiv：RSS 发现，HTML/PDF 获得论文正文

```text
https://rss.arxiv.org/rss/cs.AI
→ 提取 arXiv ID
→ /abs/{id} 核对元数据
→ /html/{id}（存在则优先）
→ /pdf/{id}（降级）
→ PyMuPDF；需要结构恢复时再用 GROBID
```

RSS 摘要只写 `abstract`。正文保留章节、页码/段落位置，引用时回到 arXiv canonical 页面。请求频率遵守公开服务要求，配置默认不高于约每 3 秒一次。参考：[arXiv RSS](https://info.arxiv.org/help/rss.html)。

## 9. OpenAlex：元数据检索，不冒充论文全文

OpenAlex 用 cursor 翻页，适合补作者、机构、引用和开放获取位置。`abstract_inverted_index` 可还原摘要，但这不是全文；若 `primary_location` 指向合法开放 HTML/PDF，交给独立论文获取器，否则保持 `metadata_abstract`。

## 10. X 与公众号

没有授权 API 时二者默认关闭。合法接入后的输出是 `SocialSignal`：帖子 ID、发布时间、作者、短文本、外链和互动快照。随后执行：

```text
解析外链 → canonical 官网/GitHub/论文 → 正常全文采集
```

找不到一手外链时进入人工审核，不进入自动精选和 RAG 事实证据。社交账号列表见 `config/social-watchlist.yaml`。

## 11. URL、幂等与增量

URL 规范化仅删除已知追踪参数（如 `utm_*`），不能任意删除业务 query。唯一性按层次处理：

- `source_id + external_id`：同一来源条目幂等；
- `canonical_url_hash`：同一 canonical URL 合并；
- `content_sha256`：完全相同正文去重；
- SimHash/Embedding：近似文章候选，不直接自动覆盖；
- Story 聚类：不同报道描述同一事件，与文章去重是不同问题。

游标只能在整个 batch 入库事务提交后推进；同事务可记录 `outbox_event` 作为事件审计，
但当前没有事件消费者。进程崩溃时允许重放，依靠唯一键、状态版本和锁实现
exactly-once effect，而不是假设 exactly-once delivery。

## 12. 错误分类

| 错误 | 是否重试 | 处理 |
|---|---|---|
| DNS/超时/408/5xx | 是，最多 3 次 | 指数退避 + 抖动 |
| 429 | 是 | 严格遵守 Retry-After/Reset |
| 401/403/验证码/登录墙 | 否 | `ACCESS_RESTRICTED`，隔离 |
| 404/410 | 有限 | 复查 canonical；持续则停用条目 |
| HTML 结构变化 | 否立即重试 | 保存 fixture，`PARSE_FAILED` |
| 正文太短/导航污染 | 否 | `FULLTEXT_REJECTED`，不得用摘要顶替 |
| 非允许 Host/私网地址 | 否 | `SSRF_BLOCKED`，安全告警 |

## 13. Definition of Done

一个来源只有同时满足以下条件才可标记 ACTIVE：

1. 发现 fixture 可重放；
2. 增量游标与 304 测试通过；
3. 最新 3 篇至少 2 篇取得合格正文或完整 Release；
4. 原始响应、canonical、发布日期和提取版本可追溯；
5. 429、超时、403、正文缺失均有确定状态；
6. 同一 batch 重放不重复入库；
7. 公开展示遵守 `public_render`，RAG 引用原始 passage。


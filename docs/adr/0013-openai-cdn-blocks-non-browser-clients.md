# ADR-0013：OpenAI 官网正文回源被 CDN 拒绝，降级为 metadata_only

日期：2026-08-01
状态：已接受
关联：`AHR-INGEST-1000` §12、`AHR-QSO-700` §4、`AHR-SOURCE-900` §5

## 背景

TASK-M1-001 实测 `openai-news`（`https://openai.com/blog/rss.xml`）时：

- RSS feed 本身可正常读取，发现 1105 条 entry；
- 回源抓取文章页（如 `https://openai.com/index/...`）**一律返回 HTTP 403**。

进一步验证：

| 检查项 | 结果 |
|---|---|
| `robots.txt` | `User-agent: * / Allow: /`，**未禁止**抓取 |
| 默认 UA `AIHotRadarBot/1.0` | 403 |
| 浏览器风格 UA `Mozilla/5.0 (compatible)` | **同样 403** |

因此这不是 robots 政策拒绝，而是 CDN 层的自动化客户端防护（TLS 指纹/JS 挑战一类），换 UA 无效。

## 决策

1. 保持现有错误分类：403 归入 `ACCESS_RESTRICTED`，**不重试、不隔离整个信源**；
2. `openai-news` 的 `content_access` 运行时降级为 `metadata_only`——只保留 RSS 提供的标题、链接、发布时间与 `discovery_summary`，不产出正文；
3. 该来源**不计入** `fulltext_parse_success_rate`（`AHR-SOURCE-900` §8 明确要求 metadata-only 单独标记）；
4. OpenAI 的一手事实改由已验证可用的替代入口覆盖：`openai-python-releases` 等 GitHub Release 源（实测 body 完整）、以及官方 changelog/docs 类来源。

## 明确不做

**禁止**采用以下任何绕过手段（`AHR-QSO-700` §4、`OUT-002`）：

- 伪装浏览器 UA 或 TLS 指纹；
- 回放登录 Cookie；
- 无头浏览器专门用于绕过 bot 防护；
- 第三方镜像站或搜索引擎快照冒充原文。

`AHR-SOURCE-900` §2 已经区分「能读取全文」与「有权公开展示」；这里再补一层：**能发现 ≠ 能回源**。发现层可用不代表正文层可得，两者必须分别记账。

## 后果

- 一手 OpenAI 资讯仍能进入系统（标题/链接/时间/摘要），但 RAG 证据不会引用其正文；
- 验收报表中该源显示 `metadata_only`，不污染全文成功率统计；
- 若 OpenAI 未来提供官方 API 或放开 CDN 限制，可将其恢复为 `full_article_extract`，无需改代码，只改配置。

## 回滚

无代码回滚项。恢复方式为在 `config/sources.yaml` 中把该源的 `content_access` 改回 `full_article_extract`。

## 落地（2026-09-28 补记）

**本 ADR 的第 2 条决策此前没有实现。** 配置仍是 `full_article_extract`，流水线也没有
「被拒后保留元数据」的分支：每篇文章 403 → 单条异常 → 回滚，整轮仍记 `SUCCESS`。
生产 09-28 实测：每轮发现 154 条、抓取 0 条，库内 0 条；`/health/sources` 的停滞告警
已连续触发 5,466 次，无人处理。

实现方式与原文措辞的对应：

- **配置**：`openai-news` 改为 `content_access: metadata_abstract`（「仍请求原文，被允许时取」），
  `public_render: metadata_link`。回滚仍如上文，只改配置。
- **流水线**：`metadata_abstract` 信源的文章页返回 401/403 时，写入一条 `METADATA_ONLY` 内容：
  正文为空，`discovery_summary` 保留 feed 简介，`extraction_method = discovery_metadata`，
  `fulltext_attempt.reason_code = ARTICLE_ACCESS_RESTRICTED`，`raw_document.http_status` 记 403。
  写入即推进游标，同一篇不会被反复请求。全文信源的 403 行为不变：仍是失败，不存标题行。
- **展示而不引用**：处理阶段用标题 + 简介做一次富化（提示词明确「未取得正文，只复述简介」），
  `attributes.enrichment_basis = discovery_summary`；切块只选有正文的修订，所以这类内容
  **永远没有分块、不会成为 RAG 证据**，只在列表、详情和厂商页出现，并链接原文。

验证：单元测试覆盖两种信源的 403 分支与处理阶段的三条 SQL；本地真实 PostgreSQL + 生产
同款 RSS（1,230 条）+ 模拟 403 跑通：5 条入库、0 分块、全部通过公开列表门槛，
页面显示中文标题、发布时间与「阅读原文」。证据见
[`../status/evidence/openai-metadata-listing-dates-20260928.md`](../status/evidence/openai-metadata-listing-dates-20260928.md)。

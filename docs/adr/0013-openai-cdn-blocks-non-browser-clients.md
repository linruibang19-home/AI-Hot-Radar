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

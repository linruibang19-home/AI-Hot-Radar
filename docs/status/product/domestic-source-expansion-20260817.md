# 中文信源扩充与全文门禁证据（2026-08-17）

本文记录 `TASK-M1-002｜全文回源与信源健康门禁` 下的一次增量，不代表所有中文站点均已开放。

## 结论

`config/sources.yaml` 仍登记 140 个来源；允许启动探测的来源由 124 增至 126。新增启用：

| 来源 | 发现入口 | 正文入口 | 激活依据 |
|---|---|---|---|
| 智东西 | `https://zhidx.com/sitemap.xml` | canonical 文章页 | robots 可访问、离线 fixture、3/3 HTTP 全文 canary |
| 字节跳动 Seed | `https://seed.bytedance.com/sitemap.xml` | canonical 文章页 | robots 可访问、离线 fixture、3/3 HTTP 全文 canary |

两者均执行“发现 URL → 回源文章 → 抽取标题/正文 → 全文门禁 → PostgreSQL 持久化”。Sitemap 只负责发现，`<lastmod>` 只参与排序，不能作为最终发布时间或正文证据。

## 实现修复

1. `HtmlListingAdapter` 增加 Sitemap `<loc>/<lastmod>` 解析，并把每轮候选限制在 `max_documents` 最新窗口，避免首次启用触发历史洪泛。
2. 游标只记录已经完成正文抽取与持久化的 external id；瞬时失败不会永久跳过。
3. Sitemap 没有标题时，从文章 metadata 或 HTML `<title>` 回填，避免把站点名写成所有文章标题。
4. 两个来源各自提供经过裁剪的 Sitemap 与文章页 fixture；fixture 只保留结构与测试文本，不复制完整第三方文章。

## 验证证据

测试环境：Windows、Python 3.12、本仓库工作树，2026-08-17。

```text
目标适配器/全文门禁测试：42 passed
Python 全量测试：926 passed, 2 skipped
ruff：All checks passed
mypy：Success, 87 source files
规范校验：SPEC VALIDATION PASSED, sources=140
```

本地 Compose 控制采集曾分别持久化 3 篇智东西和 3 篇 Seed 文章，全文门禁均为 `ACCEPTED`；抽取正文样本长度为：智东西 866–2947 字符、Seed 4373–17254 字符。该数字只证明抽取链可工作，不是生产吞吐承诺。

## 有意保持关闭的来源

| 来源 | 当前阻塞 | 决策 |
|---|---|---|
| 机器之心 | 列表/文章为客户端渲染壳，普通 HTTP 无稳定正文 | 不启用，先实现合法可回放适配器 |
| InfoQ 中文 AI | 公开页面存在，但稳定文章发现规则尚未验证 | 不启用，补 fixture 与发现门禁 |
| 36氪 AI | 访问控制/反自动化明显 | 不绕过，不启用 |
| ModelScope 头条 | 页面为 JS 壳，正文回源不稳定 | 不启用 |
| 微信公众号、X | 缺少授权适配器 | 仅保留 watchlist 线索，不入正文语料 |

因此，本次改动提升了中文与国内机构来源覆盖，但不会为了数量牺牲正文真实性、访问边界或 RAG 证据质量。

## 生产观察项

- 部署后同步来源注册表，确认两来源从 `PROBING` 经连续成功进入 `ACTIVE`；
- 核查文章标题、canonical URL、正文门禁结果和后续分块；
- 观察至少 24 小时的错误率、重复率和中文结构化成功率；
- 若站点结构变化，状态机应降级/隔离，而不是继续向公开页面和 RAG 发布坏数据。

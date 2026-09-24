# M1 Canary 验收证据

生成时间：2026-08-01（周六）｜任务卡：TASK-M1-001

| 指标 | 结果 |
|---|---|
| 已启用信源探测数 | 118 |
| ACTIVE（拿到真实全文） | 85 |
| 抽样文档数 | 246 |
| 取得完整正文 | 231 |
| **全文成功率** | **93.9%** |

## 状态分布

| 状态 | 数量 | 含义 |
|---|---:|---|
| ACTIVE | 85 | 发现与全文均正常 |
| DEGRADED | 3 | 能发现但正文失败 |
| METADATA_ONLY | 1 | 仅元数据/摘要 |
| QUARANTINED | 2 | 发现阶段即失败 |
| UNSUPPORTED_PROFILE | 27 | 适配器待 TASK-M1-003 实现 |

## ACTIVE 信源（按 profile）

| profile | ACTIVE 数 |
|---|---:|
| arxiv_feed_paper | 7 |
| author_feed_to_article | 9 |
| github_release_api | 53 |
| rss_to_article | 16 |

## 未达 ACTIVE 的信源及原因

| 信源 | 状态 | 原因 |
|---|---|---|
| openai-news | DEGRADED | CDN 拒绝非浏览器客户端（见 ADR-0013），robots 允许但 403 |
| andrew-ng-the-batch | QUARANTINED | feed URL 已失效（404），需更新配置 |
| apple-machine-learning | DEGRADED | 同上，CDN bot 防护 |
| jay-alammar | METADATA_ONLY | 文章确实较短，未达 300 字符门槛 |
| microsoft-ai-blog | QUARANTINED | feed URL 已下线（410），需更新配置 |
| venturebeat-ai | DEGRADED | 站点限流 429 |

完整逐源数据见 [m1-canary-evidence.json](m1-canary-evidence.json)。
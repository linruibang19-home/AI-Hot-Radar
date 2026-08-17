# 中文信源扩充与全文门禁证据（2026-08-17）

本文记录 `TASK-M1-002｜全文回源与信源健康门禁` 下的一次增量，不代表所有中文站点均已开放。

## 结论

`config/sources.yaml` 仍登记 140 个来源；允许启动探测的来源由 124 增至 128。新增启用：

| 来源 | 发现入口 | 正文入口 | 激活依据 |
|---|---|---|---|
| 智东西 | `https://zhidx.com/sitemap.xml` | canonical 文章页 | robots 可访问、离线 fixture、3/3 HTTP 全文 canary |
| 字节跳动 Seed | `https://seed.bytedance.com/sitemap.xml` | canonical 文章页 | robots 可访问、离线 fixture、3/3 HTTP 全文 canary |
| 阿里云官方 AI 博客 | `https://developer.aliyun.com/blog/?contentType=12` | `/article/<数字>` | robots 可访问、限定跨路径规则、离线 fixture、3/3 生产全文 canary |
| 腾讯云 AI 团队 | `https://cloud.tencent.com/developer/team/cloudAi` | `/developer/article/<数字>` | robots 可访问、限定跨路径规则、离线 fixture、3/3 生产全文 canary |

四者均执行“发现 URL → 回源文章 → 抽取标题/正文 → 全文门禁 → PostgreSQL 持久化”。其中 Sitemap
来源的 `<lastmod>` 只参与发现排序，不能作为最终发布时间或正文证据。

## 实现修复

1. `HtmlListingAdapter` 增加 Sitemap `<loc>/<lastmod>` 解析，并把每轮候选限制在 `max_documents` 最新窗口，避免首次启用触发历史洪泛。
2. 游标只记录已经完成正文抽取与持久化的 external id；瞬时失败不会永久跳过。
3. Sitemap 没有标题时，从文章 metadata 或 HTML `<title>` 回填，避免把站点名写成所有文章标题。
4. 两个来源各自提供经过裁剪的 Sitemap 与文章页 fixture；fixture 只保留结构与测试文本，不复制完整第三方文章。
5. 动态列表适配器只为显式配置的来源允许跨目录发现，并且只接受
   `/article/<数字>` 或 `/developer/article/<数字>`；课程、产品和其他导航链接不会进入抓取队列。
6. 阿里云与腾讯云的 listing/article fixture 同样经过全文门禁回放；页面结构变化时应降级或隔离，
   不能把列表摘要当作正文继续发布。

## 验证证据

测试环境：Windows、Python 3.12、本仓库工作树，2026-08-17。

```text
本轮信源适配器/全文门禁测试：32 passed
Python 全量测试：931 passed, 2 skipped
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
| 华为开发者 AI 聚合页 | 当前入口是宽泛社区/旧版聚合页，且文章会跨到不同主机；没有稳定、可回放的同站官方文章流 | 不启用，不把跨站社区内容伪装成华为官方博客 |
| 微信公众号、X | 缺少授权适配器 | 仅保留 watchlist 线索，不入正文语料 |

因此，本次改动提升了中文与国内机构来源覆盖，但不会为了数量牺牲正文真实性、访问边界或 RAG 证据质量。

## 生产落地证据

生产环境于 2026-08-17 部署不可变镜像 `sha-f6353db1fc54c45ba891118ee8b85fd50e1d78f8`，部署脚本完成全容器健康检查和公开页面/API 冒烟测试。随后暂停自动调度器，执行来源注册表同步与每源 3 篇的受控回放，最后恢复调度器。

| 来源 | 运行状态 | 入库原文 | 正文门禁 | 正文长度 | 结构化状态 | 活跃切块 | 向量覆盖 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 智东西 | `ACTIVE` | 3 | 3/3 `ACCEPTED` | 866–2947 字符 | 3/3 `ENRICHED` | 4 | 4/4 |
| 字节跳动 Seed | `ACTIVE` | 3 | 3/3 `ACCEPTED` | 4373–17254 字符 | 3/3 `ENRICHED` | 8 | 8/8 |

下游单次流水线实际完成：6 篇结构化、12 个切块、12 个 `BAAI/bge-m3` 向量、0 个 enrichment 失败、0 个 embedding 失败；事件聚类、热度、精选候选与日/周/月报告快照随后刷新。这里的 3 篇/来源是上线 canary 的受控样本量，不是信源长期上限；持续采集由 120 秒调度循环按各来源轮询计划执行。

### 仍需观察

- 观察至少 24 小时的错误率、重复率和中文结构化成功率；
- 关注 Sitemap 更新窗口与站点结构变化，避免历史洪泛或游标漏抓；
- 若站点结构变化，状态机应降级/隔离，而不是继续向公开页面和 RAG 发布坏数据。

## 第二批官方大厂来源生产证据

2026-08-17 部署 `v0.1.17` / `sha-b6e23ae8ac189a30b2bc8e29a8a19590aecbe1a5` 前，先生成
182 MiB PostgreSQL custom-format 备份并验证 SHA-256。发布流水线的 Java、Web、Python、Flyway、
规范校验与三张镜像构建全部通过；生产 preflight、10 容器健康等待和公开 smoke 通过。

部署后暂停 `scheduler` 与 `pipeline`，同步 140 源注册表，再对阿里云、腾讯云分别限定最多 3 篇：

| 来源 | 运行状态 | 入库原文 | 正文门禁 | 正文长度 | 结构化状态 | 活跃切块 | 向量覆盖 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 阿里云官方 AI 博客 | `ACTIVE` | 3 | 3/3 `ACCEPTED` | 11304–31247 字符 | 3/3 `ENRICHED` | 30 | 30/30 |
| 腾讯云 AI 团队 | `ACTIVE` | 3 | 3/3 `ACCEPTED` | 735–7753 字符 | 3/3 `ENRICHED` | 7 | 7/7 |

限定后处理实际使用 22092 个输入 token、4877 个输出 token、7168 个命中缓存 token。一次模型响应返回
33 个实体，超过 Pydantic `max_length=25`，被 schema 门禁拒绝后进入一次限定修复重试；最终 6/6 成功、
0 个 enrichment 失败。这证明模型输出校验与修复分支在真实生产输入上生效，而不是只存在于测试中。

恢复自动 worker 后的生产快照为：140 个登记信源、109 个运行态 `ACTIVE`、2594 条内容、11603 个
活跃切块且 11603/11603 已向量化、2121 个 Story、232 次 RAG 查询、990 条引用、21 份报告、Flyway
V026。这里的 `configured_enabled=128` 是允许调度的配置数，`runtime_state=ACTIVE` 是通过最近运行门禁
的动态状态，两者不是同一个指标。

同一轮备份在隔离库恢复出 `140|2588|11646|2116|21|026`，分别对应
source/content/chunk/story/report/Flyway；恢复库随后自动删除。恢复快照略小于继续运行后的生产读数，
属于备份完成后的正常增量采集。

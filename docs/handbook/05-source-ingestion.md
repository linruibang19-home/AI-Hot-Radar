# 05｜信源、采集与全文门禁

## 1. 信源系统的三层配置

| 层 | 文件 | 作用 |
|---|---|---|
| 注册表 | `config/sources.yaml` | 公开来源、profile、优先级、发现 URL、策略 |
| 通用行为 | `config/ingestion-profiles.yaml` | 九类 adapter 的超时、回源、门禁和字段规则 |
| 站点差异 | `config/site-overrides.yaml` | 少量 selector/canonical 差异，不把站点写死在代码 |

受限社交目标在 `config/social-watchlist.yaml`，没有授权 adapter 时保持禁用，只能作为待办线索。

## 2. Adapter 是策略，不是每个站一套爬虫

九类 profile 覆盖 RSS 回源、官方 changelog、GitHub release、repo activity、arXiv、公开 JSON API、
静态列表、动态列表和作者 feed。Adapter 输出统一的 discovered document，下游不需要知道它
来自 RSS 还是 API。

## 3. 完整采集步骤

```text
source 到期
→ SKIP LOCKED 领取
→ 条件请求（ETag/Last-Modified/cursor）
→ Adapter 发现候选
→ URL 规范化和 SSRF 校验
→ 保存原始响应
→ 必要时回源 canonical 文章
→ JSON-LD/Trafilatura/Readability/selector 抽正文
→ FulltextGate
→ item/revision/chunk 幂等写入
→ 更新 cursor、source health 和 next_poll_at
```

Cursor 只能在 batch 持久化成功后推进。反过来会产生“游标已走、内容没落”的永久缺口。

## 4. 全文门禁解决什么

门禁不是简单长度判断。它需要排除：

- RSS 摘要被当成全文；
- listing/navigation/cookie banner；
- 登录墙、验证码、付费墙；
- 只有标题和链接的空 release；
- 重复模板占比过高；
- 解析器异常产生的乱码；
- 不允许公开/引用的内容。

门禁失败要保存 reason 和 fixture，而不是把摘要补进正文。METADATA_ONLY 来源可展示元数据和
原文链接，但不能进入要求原文支持的 RAG 事实通道。

## 5. 外部调用工程约束

- 连接/读取超时；
- 只对网络失败、429、5xx 做有限重试；
- 尊重 `Retry-After`；
- 每 host 限速和并发边界；
- User-Agent 声明；
- 重定向每一步重新做 SSRF/host 策略；
- 记录 trace id、状态码、耗时和重试次数；
- 一个源失败不拖垮全局。

## 6. Source Health 状态

| 状态 | 含义 | 是否进入常规采集 |
|---|---|---|
| ACTIVE | 连续满足发现/全文/时效要求 | 是 |
| PROBING | 新源或恢复观察 | 受控、小流量 |
| QUARANTINED | 连续失败或策略风险 | 否，等待修复/重放 |
| METADATA_ONLY | 合法拿到元数据但无合格全文 | 仅元数据用途 |
| DISABLED | 配置或运营关闭 | 否 |

后台页面读取数据库动态状态，但不会自动编辑 YAML。修复 adapter 后要用 replayable fixture 和
fulltext gate 重新验收，不能只点“启用”。

## 7. 发布时间语义

- 官方精确时间：显示时分；
- arXiv/RSS 只有批次或日期精度：显示日期/批次，不伪造 12:00；
- 没有发布日期：`published_at` 保持空，单独记录 `observed_at/fetched_at`；
- UI 的“今日”按产品时区分组，但不能改写原始发布时间。

## 8. 失败与恢复

Scheduler 对连续失败指数退避并加入 jitter。解析器变化时先保存失败样本，再修改 override/adapter、
补 fixture、重放并观察；不要在生产手工改正文。对 403/验证码应降级策略，不进行绕过。

## 9. 关键代码

- `apps/ai-service/src/ahr/ingestion/scheduler.py`
- `apps/ai-service/src/ahr/ingestion/pipeline.py`
- `apps/ai-service/src/ahr/ingestion/repository.py`
- `apps/ai-service/src/ahr/ingestion/http.py`
- `apps/ai-service/src/ahr/ingestion/probe.py`
- `apps/ai-service/tests/fixtures/`

## 10. 面试追问

**为什么不直接买新闻 API？** 因为产品需要官方更新、GitHub、模型卡、论文和可定位正文；聚合
API 的授权、完整性、时效和证据定位不可统一保证。

**为什么不用一个通用爬虫？** 发现、正文、游标和政策因 profile 不同；用声明式 profile
复用工程约束，同时保留少量站点 override，能避免 140 份不可维护脚本。


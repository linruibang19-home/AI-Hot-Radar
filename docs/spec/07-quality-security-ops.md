# 07｜质量、安全、合规与运维

文档 ID：`AHR-QSO-700`

## 1. 测试金字塔

| 层 | 重点 |
|---|---|
| 单元测试 | URL 规范化、时间解析、指纹、评分、RRF、状态机 |
| 契约测试 | OpenAPI、Java DTO/Pydantic、枚举和 Problem JSON |
| 集成测试 | PostgreSQL/pgvector、Redis、Flyway、outbox、幂等 |
| 采集 fixture | RSS/Atom/HTML 结构变化、编码、空字段、429/304 |
| E2E | 首页→详情→Story→Radar→引用原文；后台失败重试 |
| RAG 离线评测 | 检索、引用、groundedness、拒答和延迟成本 |
| 故障演练 | LLM 429、信源超时、Redis 不可用、Worker 重启、重复消息 |

外部站点测试必须使用已脱敏 fixture，CI 不依赖实时互联网；上线验收另跑 smoke test。

## 2. CI 门禁

- format/lint/typecheck；
- 单元和契约测试；
- Flyway 从空库与上一个发布版本升级；
- 依赖漏洞与 secret scan；
- 前端构建与关键页面无障碍测试；
- 影响 RAG 的变更跑最小黄金集；合并到 release 前跑全量黄金集；
- 覆盖率是辅助指标，核心状态机和评分规则分支覆盖 ≥ 90%。

## 3. 安全

- 密钥只进入 secret/env，仓库仅 `.env.example`；
- 管理端最小权限 RBAC，关键操作二次确认；
- URL 抓取防 SSRF：仅 `http/https`，DNS/IP 解析后禁止私网、环回、metadata 地址，重定向每跳重检；
- HTML 清洗后展示，禁止原样注入；
- Markdown 禁止任意 HTML；
- 文件类型、大小、解压比和处理时间设上限；
- Prompt injection：网页内容始终标记为不可信数据，不能改变系统指令或调用权限；
- RAG 工具只读，生成模型不能直接执行管理动作；
- 日志脱敏 Authorization、Cookie、API key、邮箱和原始 Prompt 中的个人数据。

## 4. 版权与来源政策

- 尊重 robots、站点条款、付费墙和下架请求；
- 公共页面优先展示摘要、短节选和原文链接；
- `config/sources.yaml.content_access`、`public_render` 与 profile 决定读取、内部索引和公开展示边界；
- `config/social-watchlist.yaml` 中目标默认关闭，只能使用授权适配器；
- 明确区分原始来源与平台生成摘要；
- 对第三方图片默认不重新托管，使用允许的缩略图或自有视觉；
- X/公众号仅在有合规接口时启用；不得以爬虫绕过访问控制。

## 5. 可观测性

所有服务使用 OpenTelemetry trace，字段至少有：

```text
request_id, trace_id, service, operation,
source_id, crawl_run_id, task_id,
item_id, story_id, rag_query_id,
attempt, status, latency_ms, error_code,
model, prompt_version, token_in, token_out, cost_estimate
```

指标：

- source success/latency/new items/304/429；
- queue/outbox lag、retry、dead-letter；
- parse success/text length/quality fallback；
- LLM error/token/cost/schema failure；
- cluster size、merge/split override；
- index lag、retrieval latency、empty rate；
- citation correctness sample、abstention rate；
- API RED 指标、DB pool、Redis hit rate；
- email success/bounce/unsubscribe。

## 6. 告警与 SLO

| 告警 | 阈值 |
|---|---|
| P0 信源连续失败 | 3 次或 60 分钟无成功 |
| 全局入站停滞 | 2 小时无新内容且非预期 |
| Dead letter | 15 分钟内 > 10 或单任务反复失败 |
| RAG 空检索率 | 30 分钟 > 25% |
| 引用解析失败 | 任意发布回答发生即告警 |
| API 5xx | 5 分钟 > 2% |
| 数据库磁盘 | > 75% warning，> 85% critical |

## 7. 备份与恢复

- PostgreSQL 每日全量 + WAL/PITR（上线后）；
- 配置、迁移和 Prompt 入 Git；
- 对象存储开启版本/生命周期；
- Redis 不要求备份核心业务状态；
- 每月至少一次恢复演练；
- MVP RPO ≤ 24h、RTO ≤ 4h，正式公测目标 RPO ≤ 1h、RTO ≤ 2h。

## 8. RAG 发布门禁

上线前满足：

- entity/time planner accuracy ≥ 0.90；
- Recall@20 ≥ 0.85；
- citation completeness ≥ 0.95；
- citation correctness ≥ 0.90；
- 空答案/诱导题 abstention accuracy ≥ 0.90；
- 关键问题无“引用存在但不支持结论”的 P0 缺陷；
- 失败回答能用 `rag_query_id` 复现计划、候选、版本和证据。

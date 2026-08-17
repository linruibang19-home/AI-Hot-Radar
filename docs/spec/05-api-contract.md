# 05｜API 与内部任务契约

文档 ID：`AHR-API-500`

## 1. 公共约定

- Base path：`/api/v1`；
- JSON 字段使用 `camelCase`，数据库使用 `snake_case`；
- 时间为带 `Z` 或 offset 的 ISO 8601；
- 列表使用 cursor，不使用深 offset；
- 每个响应返回 `X-Request-Id`；
- 缓存读接口返回 `ETag`，支持 `If-None-Match` 和 304；
- 429 必须返回 `Retry-After`；
- 错误使用 `application/problem+json`。

错误示例：

```json
{
  "type": "https://aihotradar.example/problems/invalid-time-range",
  "title": "Invalid time range",
  "status": 400,
  "detail": "from must be earlier than to",
  "instance": "/api/v1/items",
  "requestId": "req_01...",
  "errors": [{"field":"from","code":"range.invalid"}]
}
```

## 2. 只读内容 API

| Method | Path | 说明 |
|---|---|---|
| GET | `/selected` | 精选游标列表 |
| GET | `/items` | 全部动态与过滤 |
| GET | `/items/{idOrSlug}` | 资讯详情 |
| GET | `/stories` | 热点事件列表 |
| GET | `/stories/{idOrSlug}` | 事件详情与时间线 |
| GET | `/topics` | 主题目录 |
| GET | `/topics/{slug}` | 主题详情 |
| GET | `/reports/latest?period=daily` | 最新报告 |
| GET | `/reports/{period}/{key}` | 指定报告 |
| GET | `/search` | 关键词/过滤搜索 |
| GET | `/sources/public` | 公开信源说明 |

`GET /items` 参数：`cursor,limit<=50,from,to,company,product,topic,type,sourceTier,source,language,primaryOnly,storyOnly,q,sort`。

列表 envelope：

```json
{
  "data": [],
  "page": {"nextCursor":"opaque|null","hasMore":false},
  "meta": {"requestId":"req_...","generatedAt":"2026-07-31T00:00:00Z"}
}
```

Cursor 必须签名或不可推断，并包含排序锚点与过滤 hash；过滤条件变化时旧 cursor 返回 400。

## 3. 增量同步

| Method | Path | 说明 |
|---|---|---|
| GET | `/sync/selected/snapshot` | 首次完整快照 |
| GET | `/sync/selected/changes?cursor=` | 新增、更新、撤选/删除 |

Change：

```json
{
  "op":"upsert|remove",
  "entityType":"item|story",
  "id":"uuid",
  "version":12,
  "changedAt":"ISO-8601",
  "payload":{}
}
```

客户端只有持久化新 cursor 后才视为同步成功；服务端至少保留 30 天 change log，过期 cursor 返回 410 并要求重新 snapshot。

## 4. RAG API

### POST `/rag/queries`

```json
{
  "question":"最近七天 OpenAI 有什么重要更新？",
  "conversationId":"uuid|null",
  "timezone":"Asia/Shanghai",
  "answerFormat":"brief",
  "filters":{"sourceTiers":["primary","authoritative_secondary"]}
}
```

返回 202：`queryId,conversationId,status,streamUrl`。SSE 事件：

```text
event: plan       data: {retrievalPlanSummary}
event: retrieval  data: {storyCount,evidenceCount,degradedChannels}
event: delta      data: {text}
event: citation   data: {number,title,url,publishedAt,sourceTier}
event: done       data: {answerId,metrics}
event: error      data: {problem}
```

服务端必须在发送 `citation` 前从数据库解析 passage ID，不转发模型伪造 URL。取消连接应尝试取消下游生成并记录 `client_cancelled`。

### GET `/rag/answers/{id}`

返回最终回答、解析时间范围、引用、限制、检索时间和生成版本；不公开模型隐藏思维过程。

## 5. 管理 API

所有 `/admin/**` 需要 RBAC + CSRF/同源保护：

- `GET/PATCH /admin/sources/{id}`；
- `GET /admin/sources/summary`：返回当前环境 PostgreSQL 中的登记/启用/关闭数、配置版本和数据更新时间；
- `POST /admin/sources/{id}/run`；
- `GET /admin/jobs`；
- `POST /admin/jobs/{id}/retry`；
- `POST /admin/stories/merge`；
- `POST /admin/stories/{id}/split`；
- `PATCH /admin/items/{id}`；
- `POST /admin/reports/{id}/publish`；
- `POST /admin/deliveries/test`。

所有变更请求要求 `Idempotency-Key`；合并/拆分等冲突敏感操作要求 `If-Match` 版本。

## 6. Java ↔ Python 内部契约

内部 API 使用 `/internal/v1`，mTLS 或内网 token；只传标识和版本：

```json
{
  "taskId":"uuid",
  "taskType":"FETCH|PARSE|ENRICH|CLUSTER|EMBED|RAG",
  "aggregateId":"uuid",
  "inputVersion":7,
  "traceId":"string",
  "deadlineAt":"ISO-8601"
}
```

结果只能更新与 `inputVersion` 对应的聚合；过期结果返回 409 并标记 `STALE_RESULT`。契约先写 JSON Schema/OpenAPI，再生成 Java DTO 与 Pydantic Model；禁止两端手工维护不同枚举。

## 7. 限流建议

| 路由 | 匿名 | 登录用户 | 管理员 |
|---|---:|---:|---:|
| 内容读 | 120/min/IP | 300/min/user | 600/min |
| 搜索 | 30/min/IP | 90/min/user | 180/min |
| RAG | 3/min、20/day | 10/min、100/day | 配额制 |
| 管理变更 | 禁止 | 禁止 | 60/min |

阈值配置化；搜索引擎爬虫与可信同步客户端使用独立策略，不以 User-Agent 单独放行。

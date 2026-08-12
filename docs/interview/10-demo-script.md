# 10｜现场演示与故障备用脚本

## 演示前检查

- 公网 `/`、`/reports`、`/ask`、`/eval`、`/ops`、`/admin/sources` 返回 200；
- 准备一个可答问题、一个时间问题、一个带假前提的不可答问题；
- 预先打开一条已保存 `/ask/{id}`，避免模型或网络故障时无内容；
- README 截图不含邮箱、令牌、密钥、服务器管理信息和浏览器隐私；
- 记录线上运行 SHA、当天内容量和 `/eval` snapshot metadata；
- 本地保存五张截图和 3–5 分钟录屏。

## 五分钟主脚本

### 0:00–0:35 项目价值

打开首页：一句话说明 140 信源、全文回源、Story/精选/报告和证据 RAG。强调当前计数是动态快照。

### 0:35–1:25 内容链

点击一条精选到原文/事件，解释一手来源、批次/精确时间、多源 Story 与推荐理由。指出 RSS 只发现，
RAG 最终引用 canonical 正文 chunk。

### 1:25–2:35 RAG

打开 `/ask` 提问，再进入结果页：

1. 展示解析后的时间范围和证据数；
2. 点句级引用到来源卡与原文；
3. 展开“为什么是这些证据”，讲 dense/sparse、rerank、Story 折叠和淘汰原因；
4. 提带假前提问题，展示拒绝错误前提而不是顺着编。

### 2:35–3:25 质量门

打开 `/eval`，先说这是固定 90 题发布快照，不随在线提问变化；展示 Recall、引用覆盖、支持度、误拒
和诱导题，再指出 B2/B8/B13 负结果和 GEN-FIX 原假设被证伪。

### 3:25–4:15 报告与邮件

打开 `/reports` 切换日/周/月；展示订阅弹窗。解释 PENDING → 邮件确认 → ACTIVE → 时区 08:30
→ PUBLISHED 报告幂等投递；发送的是保存报告，不重新临时生成。

### 4:15–5:00 生产和取舍

打开 `/ops` 与 `/admin/sources`：区分实时运行聚合和手动刷新的信源快照；说明 2C4G、Compose、
pgvector 的当前边界，以及按什么证据引入队列、独立搜索或更大机器。

## 十分钟扩展脚本

在五分钟基础上增加：

- 画三个服务职责和 PostgreSQL/Redis 边界；
- 讲一条 URL 经全文门、revision、schema、chunk、embedding、Story 到 RAG；
- 用 GEN-FIX 完整讲一次 S/T/A/R；
- 讲 SHA 镜像、Caddy、内部端口、备份/SHA/隔离恢复；
- 主动说一个当前召回缺口和管理写 UI 未做的安全原因。

## 网络或模型故障时

1. 不反复点击在线生成；打开预存 `/ask/{id}` 展示同样的引用和轨迹；
2. 网站不可达时按顺序使用 README 五张截图和录屏；
3. GitHub 不可达时使用本地 README 与 `docs/interview/`；
4. 明确“演示依赖故障”和“产品已保存证据”区别，不伪造实时结果；
5. 若只剩白板，按 `09-system-design-whiteboard.md` 的 5 分钟顺序。

## 面试官要求看代码时

按问题进入，不从仓库根目录漫游：

| 问题 | 代码/证据入口 |
|---|---|
| 采集与全文 | `apps/ai-service/src/ahr/ingestion/`、`config/ingestion-profiles.yaml` |
| 切块与结构化 | `apps/ai-service/src/ahr/processing/` |
| RAG | `apps/ai-service/src/ahr/rag/`、`docs/status/eval/` |
| API/订阅 | `apps/core-api/src/main/`、Flyway V023 |
| 前端 | `apps/web/app/`、`apps/web/lib/` |
| 部署 | `infra/compose/`、`infra/scripts/`、`.github/workflows/release.yml` |
| 决策与反例 | `docs/adr/`、`docs/status/project-status.md` |

先指出文件职责，再选一个函数/测试讲输入、状态、失败和验证；不要一次打开几十个文件。

## 收尾话术

> 这个项目最想证明的不是我能调用多少模型，而是我能把模型放进可追踪的数据、质量和生产边界：
> 找不到就拒答，找到了能回原文，实验不好看也保留，线上失败能恢复。下一步会先扩大噪声和用户
> 反馈集、迁移自有发件与服务器，而不是在没有容量证据时堆更多中间件。

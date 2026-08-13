# TASK-M5-003 非阻塞报告发布状态机与审核 API

日期：2026-08-11

功能提交：`6030a71`

决策：ADR-0025

## 1. 结论

报告审核不会阻塞 AI 动态、每日精选、Story、RAG 或采集流水线。审核门只决定一份已经
生成的日报、周报或月报能否公开和正式发送：

- 合格：`PUBLISHED`，站内自动可见；
- 不合格：`REVIEW_REQUIRED`，等待操作员处理；
- 人工撤回：`WITHDRAWN`，pipeline 不会自动恢复；
- 迁移前草稿：用同一确定性门禁回填，不直接放行。

当前数据库 14 份历史报告全部通过门禁：日报 10、周报 3、月报 1，均为 PUBLISHED。
站内报告会随 pipeline 正常生成与发布。邮件仍是手工 CLI；订阅者管理与定时投递不在本卡，
不能把“站内自动发布”误写成“已经自动群发邮件”。

## 2. 发布门细节

生成器在写 `report` 前检查：

1. 周期最少条目数：日报 5、周报 5、月报 10；
2. 摘要非空；
3. 每条内容都有 HTTP(S) 原文 URL、标题和来源；
4. 每条内容已经归入 Story；
5. 模型生成的摘要必须通过严格 Pydantic JSON schema，非法输出回退到确定性摘要。

门禁结果和原因写入 `generation_meta.publicationGate`。报告重算可更新 PUBLISHED 或
REVIEW_REQUIRED，但不会覆盖人工 WITHDRAWN。公开列表、公开详情和正式邮件都只接受
PUBLISHED；`send-report --dry-run` 可预览非正式状态。

## 3. 管理与安全

新增受保护的报告列表、详情、发布和撤回 API。写操作要求：

- OPERATOR Bearer；VIEWER 实测为 403；
- `X-Confirm-Target` 必须精确回显报告 UUID；
- 8–200 字符 `Idempotency-Key`；
- 幂等结果持久化到 PostgreSQL，同一键同一请求只执行一次，冲突键拒绝；
- 未完成请求五分钟后可安全回收；
- 成功、拒绝和失败写入 `admin_audit`，不记录凭据。

PostgreSQL 仍是唯一事实来源；Redis 不保存发布状态。V022 只增加报告状态约束和
`admin_idempotency`，没有改变内容、精选或 RAG 实体。

## 4. 测试证据

| 门禁 | 命令/结果 |
|---|---|
| Python 风格 | `ruff check` + `ruff format --check`：通过 |
| Python 类型 | `mypy src`：86 source files，无错误 |
| Python 专项 | `pytest -q tests/test_report.py tests/test_email.py tests/test_worker.py`：76/76 |
| Python 全量 | `pytest -q`：871/871，1 个既有 Starlette 弃用告警 |
| Java | Maven `test`：62/62，BUILD SUCCESS |
| Flyway | 运行库 `flyway_schema_history`：V022 success=true |
| 历史回填 | DRAFT 14 → PUBLISHED 14，REVIEW_REQUIRED 0 |
| 公开报告 | daily 10、weekly 3、monthly 1；详情与 `/reports` 均 200 |
| 管理 API | 无 token 401；VIEWER 发布 403；OPERATOR 200；同幂等键重放不重复写 |
| 非阻塞检查 | `/api/v1/items` 与 `/api/v1/selected` 均返回真实条目 |
| Pipeline | 一轮完成；enriched/embedded/stories/selected/reports 均正常记录 |

Docker Hub 拉取 JRE 元数据时连接被远端重置，因此运行镜像使用已缓存的本地 JRE 层和
本次 Maven build-stage 产出的 JAR 组装；JAR 编译、62 项测试、V022 迁移和运行态均实测
通过。保留了 `ai-hot-radar-core-api:pre-report-publication` 本地回滚镜像。

ChromeCodex 在导航前仍因本机内核资源路径缺失失败，错误为
`failed to write kernel assets: 系统找不到指定的路径。 (os error 3)`。本卡没有前端改动；
报告阅读页的桌面/窄屏人工视觉门禁仍继承 TASK-M5-002 的待办，不能用 HTTP 200 替代。

## 5. 剩余风险与下一张任务卡

- 没有订阅者事实模型、退订语义或 daily/weekly/monthly 定时邮件任务；当前不能自动群发；
- 管理发布/撤回只有 API，没有浏览器写 UI，OPERATOR 凭据不得放进前端；
- 当前 14 份报告全部通过门禁，不代表门禁阈值已在长期生产分布上完成标定；应持续观察
  REVIEW_REQUIRED 原因分布；
- ChromeCodex 环境恢复后仍需补报告页桌面与窄屏视觉验收。

下一张任务卡：`TASK-M5-004｜报告订阅与定时投递闭环`。开始前必须先确认收件人来源、
退订规则和时区；失败不得反向阻塞采集、精选或站内发布。

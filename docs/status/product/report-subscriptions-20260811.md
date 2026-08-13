# TASK-M5-004 报告订阅与定时投递验收

日期：2026-08-11
状态：**生产 SMTP、双重确认和公网 UI 已上线；v0.1.6 等待下一期报告完成首封订阅投递**

> 2026-08-12 更新：生产 SMTP 和确认链路已验证，库中有 1 个 ACTIVE 日报订阅；
> `email_delivery` 暂为 0 是因为系统不补发确认前的历史期刊。v0.1.6 已将正式邮件正文从
> 原始 Markdown 改为安全 HTML，并在弹窗明确三步流程。最新证据见
> `v016-selection-email-20260812.md`。

## 1. 实现边界

- Core API 是邮箱、周期偏好、确认、退订和投递状态的唯一事实所有者；
- PostgreSQL 持久化业务事实，Redis 不保存订阅；
- Web 只暴露同源代理、订阅弹窗和显式确认/退订页，不持有 SMTP 或签名密钥；
- 现有 Python `send-report --dry-run` 保留为运维预览，不再负责订阅调度；
- 只发送确认时间之后的 PUBLISHED 报告，DRAFT、REVIEW_REQUIRED、WITHDRAWN 永不入队；
- 邮件失败只更新 `email_delivery`，不会反向阻塞报告发布或内容流水线。

架构决定见 ADR-0026，数据库变更见 Flyway V023，公共接口见 OpenAPI 1.3.0。

## 2. 投递语义

1. 用户提交邮箱、daily/weekly/monthly 周期和 IANA 时区；
2. 服务统一返回 202，避免枚举已订阅地址；同一邮箱十分钟内不重复发送确认信；
3. 24 小时 HMAC-SHA256 链接经用户显式点击后才建立 ACTIVE 订阅；
4. 每五分钟扫描（本地验收为十秒），到用户当地 08:30 后选择确认后的最新报告；
5. `(subscription_id, report_id)` 唯一键保证同一期同一收件人至多一条投递记录；
6. 多实例通过 `FOR UPDATE SKIP LOCKED` 领取，15 分钟的陈旧 SENDING 会恢复；SMTP 失败按
   10/60 分钟退避，最多三次；
7. 邮件包含站内报告链接和长效版本化退订链接，退订会使旧链接失效。

## 3. 自动化证据

| 门禁 | 结果 |
|---|---|
| Core API JDK 21 | Maven package；72 tests，0 failures |
| Web | typecheck、ESLint；Vitest 69/69 |
| 生产资产 | `test_production_delivery.py` 7/7 |
| Spec | 140 sources / 9 profiles / 38 social targets，通过 |
| 生产 preflight fixture | SMTP、签名密钥、不可变镜像和 Compose 结构检查通过 |
| 空库 Flyway | 24 migrations，最终 `023:true`，应用成功启动 |
| 现有数据卷 | V023 单迁移成功，Core API / Web / Postgres / Redis / Mailpit healthy |

## 4. Mailpit 真实闭环

使用 `acceptance-20260811@example.test` 在本地 Compose 完成：

- `POST /api/subscriptions` → `PENDING_CONFIRMATION`，Mailpit 收到一封确认信；
- 从邮件链接显式确认 → `ACTIVE`，三个周期偏好均保存；
- 插入一份只用于验收的新 PUBLISHED 日报 → Mailpit 收到正式报告；
- 正式报告包含 `/reports/daily/acceptance-20260811` 在线阅读地址；
- 从邮件链接退订 → `UNSUBSCRIBED`；
- 删除验收投递、报告、请求与订阅，重建 Mailpit 后消息数为 0。

测试没有联系外部邮箱。Local Compose 固定使用 Mailpit，即使根 `.env` 存在生产 SMTP 值也
不会误发；生产 Compose 仍只从权限 600 的目标机环境文件读取真实 SMTP。

## 5. 当前仍需补齐的生产能力

- 当前 Gmail SMTP 只适合低量试运行；仍需专用发件账号、额度/退信策略和 SPF/DKIM/DMARC；
- Chrome、扩展和原生宿主诊断均通过，但 Codex 浏览器执行内核两次因本地路径初始化失败，
  所以本卡没有桌面/窄屏点击截图证据；
- 下一期报告发布后仍需核对首封正式订阅的 `email_delivery=SENT`；
- 公网开放前宜补 IP/全局确认邮件速率限制或 CAPTCHA；当前已有每邮箱十分钟冷却，但不能
  单独抵御攻击者轮换任意地址消耗邮件信誉。
- SMTP 没有供应商幂等键；在“SMTP 已接收、数据库尚未标记 SENT”的极窄崩溃窗口，恢复任务
  可能重复发送。数据库投递事实仍唯一，但端到端 exactly-once 需要支持幂等键的邮件 API。

## 6. 下一张任务卡

按主人确认的范围进入“DeepSeek 生成模型可见与切换”：只切换总结、报告与 RAG 生成所用的
DeepSeek 模型；SiliconFlow embedding/reranker 和 1024 维向量事实保持不变。该变更需要先
写 ADR，并与内容快照、报告 `generation_meta`、RAG 查询和成本统计绑定，不能只改一个全局
环境变量。

# ADR-0025：报告发布是非阻塞输出门禁，不是内容生产总闸门

- 状态：已接受
- 日期：2026-08-11
- 相关：`AHR-FEAT-105`、`AHR-API-500` §5、`AHR-QSO-700` §3、
  `AHR-RUNBOOK-1100` §6、ADR-0019

## 背景

报告生成器固定写入 `DRAFT`，但当前公共报告 API 和手工邮件命令都不检查状态。
这造成两个相反风险：直接把公共读取改为 `PUBLISHED` 会让现有日报、周报、月报全部
消失；继续忽略状态，又会让未经门禁的草稿被当成正式出版物或邮件发送。

报告位于采集、加工、Story 和精选之后。人工审核报告不应反向阻塞这些上游，否则一次
编辑缺席就会同时冻结“全部 AI 动态”和“每日精选”，违反 `AHR-RUNBOOK-1100` 的
“日报生成失败不阻塞资讯入库”。

## 决策

### 1. 生产与发布解耦

采集、加工、Embedding、Story、热度、精选和 RAG 始终按原管线继续。报告状态只控制
报告的公共读取与正式投递，不参与 `content_item`、`selection_record` 或 Story 查询。

### 2. 报告采用四态输出状态机

```text
DRAFT -> PUBLISHED        自动门禁通过或 OPERATOR 发布
DRAFT -> REVIEW_REQUIRED  自动门禁不通过
REVIEW_REQUIRED -> PUBLISHED  OPERATOR 核验后发布
PUBLISHED -> WITHDRAWN    OPERATOR 下架
WITHDRAWN -> PUBLISHED    OPERATOR 明确重新发布
```

自动门禁只检查可确定、可重放的事实：周期最低条目数、非空摘要、每条有合法 HTTP(S)
原文、来源名和 Story。它不调用模型做第二次主观评审。门禁结果与原因写入
`generation_meta.publicationGate`。

`WITHDRAWN` 是人工锁：后续 pipeline 更新同一期报告时不得自动解除。自动门禁失败的
`REVIEW_REQUIRED` 允许下一次重新生成后再次评估，因为其原因可能是上游加工尚未完成。

### 3. 公共读取和投递只使用 PUBLISHED

公共报告列表、最新一期和详情只返回 `PUBLISHED`。管理预览位于受 ADR-0019 保护的
`/api/v1/admin/**`。正式邮件发送拒绝非 `PUBLISHED`；`--dry-run` 仍可预览草稿，且不
发送网络请求。

已有 DRAFT 不直接批量放行。pipeline 使用同一确定性门禁逐份检查，合格的历史报告
转为 `PUBLISHED`，不合格的进入 `REVIEW_REQUIRED`，保证切换公共过滤时不会无条件
清空历史档案。

### 4. 人工变更必须鉴权、确认、幂等、审计

`POST /api/v1/admin/reports/{id}/publish` 与 `/withdraw` 仅 OPERATOR 可调用，必须同时
提供 `X-Confirm-Target: {id}` 和 `Idempotency-Key`。幂等结果保存在 PostgreSQL，重复键
与相同目标返回原结果，重复键换目标返回 409。每次允许、拒绝或失败均写 `admin_audit`。

## 不做什么

- 本 ADR 不引入用户账号、浏览器 OPERATOR 凭据或 Cookie 会话；
- 不新增自动邮件时间表、订阅偏好和退订流程；
- 不把模型输出作为自动发布门禁判据；
- 不让人工审核影响 AI 动态、精选、Story 或 RAG。

## 后果

- 无人值守时，满足确定性证据条件的日报/周报/月报仍可正常更新和公开；
- 风险报告只停在报告出口，不拖住内容生产；
- 正式投递不会误发 DRAFT；测试预览仍可执行；
- 新增一张小型幂等结果表和报告状态约束，均由 Flyway 管理；
- 后续管理 UI 必须另行解决 OPERATOR 凭据输入/保管，不能把写令牌放进现有 Web 容器。

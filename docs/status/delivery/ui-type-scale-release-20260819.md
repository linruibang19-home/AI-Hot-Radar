# v0.1.20 前端字号标度与界面小字收敛（2026-08-19）

## 发布对象

- GitHub 合并提交：`0914ae9bef2ef2cc60d116ee0262d52ee63192cb`（PR #39 排版与文档、PR #40 单一星期名表）；
- Release 标签：`v0.1.20`，workflow run `32188078292`，产出三张
  `sha-0914ae9bef2ef2cc60d116ee0262d52ee63192cb` 镜像；
- 生产地址：<https://aihotradar.online>；
- 目标环境：香港 Ubuntu 22.04.5、2C4G、Docker Compose、Caddy HTTPS。

只改前端呈现与文档。不动数据库 schema、检索策略、采集、报告与生成侧配置。

## 发布门禁

| 层 | 结果 |
|---|---|
| Web | typecheck、lint、Vitest `99 / 99`、Next production build 通过 |
| Python / Java / Flyway | 通过（本次未改动） |
| 规格文档 | `validate_spec.py`、`validate_docs.py` 通过 |

## 部署后验收

`deploy-production.sh` 以 `deploy` 用户执行，`EXIT=0`，
`deploy OK: sha=0914ae9bef2ef2cc60d116ee0262d52ee63192cb`，10 个容器 Up / healthy。

线上样式表 `/_next/static/css/7f8fdc85c24c0d35.css` 实查：

| 项 | 结果 |
|---|---|
| 字号取值 | 全部为 `var(--fs-*)`，八档；另有 4 处 `clamp()` 流式标题 |
| 12px 以下的声明 | **0**（改前 42 处，最小 9px） |
| 首页大标题 | `2026年8月19日 周三 · 今天值得看的 AI 动态`（此前星期缺失） |
| `/items` 日期分组 | `周三` / `周二` / `周一`，与首页一致 |
| 旧文案残留 | 4 条抽查文案在 5 个页面上均为 0 处 |
| 供应商配置 | `usesEnvironment: true`，`credentialStorageReady: true` —— 生成侧未受影响 |
| pipeline / scheduler | `pipeline pass done in 42.91s`；`tick claimed=2 ok=2 failed=0` |

## 过程记录

**合并顺序判断错误。** PR #40 的说明里写了「两个 PR 都改 `lib/datetime.ts` 但在不同位置，合并顺序无所谓」。实际 #39 合入后 #40 立即冲突：#39 在 `formatDayLabel` 与 `formatWeekday` 之间插入 `formatToday`，而 #40 从更早的提交分出，同一位置为空。rebase 后保留两侧函数，重跑门禁通过（99 条测试）。

结论：只要两个分支触碰同一文件的相邻区域，就不能预先断言无冲突。

## 遗留

与 v0.1.19 相同，未变化：

- 主密钥仍需离机备份；
- 备份日志核对、`restore-verify`、源站入口收紧到 Cloudflare 段尚未执行；
- `main` 分支未开启保护与必需状态检查；
- 架构核查发现 ②（`api/openapi.yaml` 的 RAG 契约与实现不符）与 ③（报告陈旧判据过粗）未处理；
- `components/Timeline.tsx` 与 `ItemsFeed.tsx` 已不再持有星期名表，由 `lib/datetime.test.ts`
  的源码断言守住。

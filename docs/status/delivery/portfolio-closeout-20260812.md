# 作品集页面语义与文档封版（2026-08-12）

任务卡：TASK-M5-010。本文记录本次页面与文档变更的事实，不替代发布后的生产证据。

## 完成内容

### RAG 质量页

- `/eval` 顶部新增“静态发布评测”元数据：语料截止日期、样本量、embedding、reranker、generation model。
- 明确说明该页不会随线上提问自动变化；切换模型/提示词/切块/检索策略必须重跑固定黄金集。
- 将实时成本、延迟与错误率指向 `/ops`，避免把历史实验当运行监控。
- `scripts/build_eval_summary.py` 从评测 artifacts 生成上述 metadata，页面不手工抄两套状态。

### 信源后台

- `/admin/sources` 显示“本次读取”时间和“刷新状态”入口。
- 明确状态来自 scheduler 写入 PostgreSQL 的最新结果，页面自身不主动轮询。
- 2026-08-12 17:33 本地读取快照：ACTIVE 109、PROBING 12、METADATA_ONLY 2、QUARANTINED 1；
  这是动态运行数据，不是发布指标。

### 公开作品集

- README 增加产品一览、系统架构 Mermaid 与五张脱敏页面截图。
- `TASK-M5-011` 将 `docs/interview/` 补齐为 00–10 十一份分层材料：一页纸、业务架构、
  采集与数据、RAG、后端一致性、前端、部署安全、题库、简历 STAR、白板和演示脚本；
  旧的五份合并稿已删除，避免两套叙事继续漂移。
- 截图由本机无头 Chrome 在 `1440x1000` 生成，未包含浏览器扩展、邮箱、令牌或密钥。
- Chrome Codex/Computer Use 因本机 kernel assets 路径错误不可用，按前端调试规范降级到同机
  headless Chrome；这不是应用错误。

## 验证证据

```text
docker compose -f infra/compose/docker-compose.yml build web
PASS: Next.js 15.5.23 production build, 10 routes generated

docker run --rm -v "$PWD/apps/web:/src:ro" -w /app ahr-web-deps:latest \
  sh -lc "cp -a /src/. /app/ && npm run typecheck"
PASS

docker run --rm -v "$PWD/apps/web:/src:ro" -w /app ahr-web-deps:latest \
  sh -lc "cp -a /src/. /app/ && npm run lint"
PASS

docker run --rm -v "$PWD/apps/web:/src:ro" -w /app ahr-web-deps:latest \
  sh -lc "cp -a /src/. /app/ && npm test"
PASS: 8 files, 73 tests

GET http://localhost:3000/eval
PASS: 200; contains 静态发布评测 and 运行状态

GET http://localhost:3000/admin/sources
PASS: 200; contains 刷新状态, 不会主动轮询 and 本次读取
```

## 数据时效口径

| 页面 | 数据口径 |
|---|---|
| `/`、`/reports`、`/ops`、`/admin/sources` | 读取当前数据库；受缓存和页面刷新时点影响 |
| `/eval` 顶部门禁 | 固定黄金集、固定语料 cutoff 和固定模型的发布快照 |
| `/eval` B1–B13/GEN/LAT | 历史算法实验记录，只在新增评测 artifacts 时变化 |

## 剩余风险

- 自动 citation precision 仍不能替代高风险陈述的人审。
- 信源后台目前是只读 SSR 快照，不是告警系统或实时推送控制台。
- README 的业务计数是标注日期的历史快照；答辩时以线上页面和最新 handoff 为准。
- 发布后仍需用公网桌面/移动端复验截图路由，并在 handoff 中记录新镜像 SHA。

## 下一张任务卡

作品集材料由 `TASK-M5-011` 做最终分层收口。此后进入维护：按
`docs/status/operations/tencent-cloud-migration-readiness-20260812.md` 做新机平行恢复与备案后 DNS 切换，
后续顺序现以 `docs/status/current/handoff-20260814.md` 为准；本文件保留 08-12 封版时的结论。

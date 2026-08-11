# 上线前最终本地门禁（2026-08-11）

状态：**本地发布候选通过；生产尚未恢复**

分支：`codex/prelaunch-product-completion`

范围：邮箱订阅、DeepSeek 生成模型配置、RAG 质量/运行页以及 V023/V024 后的全栈回归。

## 1. 发布结论

代码、数据库迁移、本地运行和备份恢复已达到“可以提交并进入 CI/镜像发布”的条件，
不等于生产已经上线。旧生产镜像不含 V023/V024 与本轮 UI，服务器继续保持停止。

## 2. 自动化门禁

| 门禁 | 命令/口径 | 结果 |
|---|---|---|
| Spec | `python scripts/validate_spec.py` | 140 sources / 9 profiles / 38 social targets |
| Python | Ruff check + format、mypy、pytest | 86 files；878 passed / 2 skipped |
| Java | Java 21 容器 `mvn -B verify` | 12 suites；74 tests；0 failure/error/skip |
| Web 依赖 | `npm audit --audit-level=high` | 0 vulnerabilities |
| Web | typecheck、lint、Vitest、Next build | 71 passed；production build 成功 |
| 空库迁移 | Flyway 10 + pgvector PostgreSQL 16 | 25 migrations；V001–V024；`024:true` |
| production Compose | fixture preflight + `config --quiet` | 通过 |
| Docker Web | rebuild + recreate | healthy |

## 3. 数据与恢复

当前库：140 个信源、1915 条内容、7264 个分块且全部向量化、1498 个 Story、15 份
PUBLISHED 报告。Flyway V024，DeepSeek 当前为 `deepseek-v4-flash` version 3。

从当前数据库创建 102 MiB custom-format dump，完成 `pg_restore --list`、SHA-256、受保护
隔离库恢复和清理。恢复快照：

```text
140|1915|7264|1498|15|024
```

该演练证明应用内备份可恢复；它不能替代生产异机备份，生产 RPO/RTO 仍未关闭。

## 4. 业务 smoke

以下本地页面/API 均为 200：

- 首页、全部动态、热点、Story、主题；
- 报告列表、日报 `2026-08-11`、周报 `2026-W32`、月报 `2026-08`；
- `/ask`、`/eval`、`/ops`、`/admin/sources`、`/admin/models`；
- sitemap、Core ready、AI ready。

报告订阅完整确认/投递/退订此前已在 Mailpit 走通并清理验收数据；本轮 Java/Web 回归继续
覆盖该链路。生产 SMTP 尚未配置，不能声称外部邮箱已实收。

## 5. 未关闭的外部门禁

1. 当前分支尚未 push、PR/CI、合并和发布新不可变镜像；
2. 聊天中出现的 provider/GitHub key 必须吊销，目标机使用专用低额度新 key；
3. DeepSeek 与 SiliconFlow 控制台消费上限尚需主人确认；
4. 生产 SMTP、SPF/DKIM/DMARC 与退信策略未配置；
5. 真实 HTTPS 告警失败/恢复尚未实收；
6. 异机备份与目标机隔离恢复尚未复演；
7. ChromeCodex 因本机 kernel asset 路径错误仍无法执行桌面/窄屏视觉验收。

## 6. 下一张任务卡

继续 `TASK-M5-006`：先 push 当前分支并让同提交 CI 全绿，发布不可变镜像；再填齐生产
外部闸门、运行 fail-closed preflight 和部署脚本，最后完成公网 smoke、邮件、告警与恢复实收。

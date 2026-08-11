# TASK-M5-005 生产部署预检与恢复门禁

日期：2026-08-11
状态：**代码侧与本地真实演练通过；目标服务器动作待授权**

## 1. 本卡完成了什么

- production Compose 只暴露 Caddy 80/443，应用、数据库、Redis 均只在内部网络；
- 生产配置必须通过 `preflight.sh`：不可变 `sha-<40 hex>` 镜像、HTTPS 公网地址、
  高熵且不同的管理令牌、正整数限额、供应商消费上限与异机备份确认；
- release workflow 先复用完整 CI 验证同一提交，再构建和推送三个镜像；
- Caddy 只信任 Cloudflare 官方公网边缘网段，并严格读取 `CF-Connecting-IP`；
- 备份先做 `pg_restore --list` 目录校验，再原子发布并生成 SHA-256；
- `restore-verify.sh` 只允许受保护的隔离库名，核对五张核心表与 Flyway 后自动删除；
- 只读 monitor 检查 Core/AI/Web readiness 与备份年龄/校验和，不挂 Docker socket；
- 部署脚本串联干净工作树、当前提交 SHA、pull、健康等待和 HTTPS smoke。

## 2. 本地真实恢复证据

为获得稳定快照，只暂停 scheduler 与 pipeline；Web、Core API、AI Service 与数据库保持在线。

| 项 | 结果 |
|---|---|
| 备份文件 | `ai_hot_radar-20260811T062540Z.dump` |
| 大小 | 103,896,733 字节（约 100 MiB） |
| 目录校验 / SHA-256 | 通过 / 通过 |
| 恢复目标 | `ai_hot_radar_restore_verify`，演练后自动删除 |
| 核心快照 | source 140；content 1867；chunk 7098；story 1458；report 14 |
| Flyway | V022 |
| Worker 恢复 | scheduler、pipeline 均重新启动 |

当前库随后继续采集至 content 1868 / chunk 7102；这说明恢复脚本默认允许源库在备份后增长，
受控演练则用 `RESTORE_REQUIRE_EXACT=true` 做精确计数。

## 3. 测试证据

| 门禁 | 结果 |
|---|---|
| Python 断网容器 | Ruff、format、mypy 86 files、pytest 878/878 |
| Java 21 容器 | Maven verify 62/62，BUILD SUCCESS |
| Spec | 140 sources / 9 profiles / 38 social targets |
| production Compose | 默认与 tools profile 均可解析；仅 Caddy 发布端口 |
| Caddy | `caddy:2-alpine caddy validate` 通过 |
| preflight | 结构 fixture 显式允许时通过，默认拒绝 |
| monitor | 在当前 Compose 网络 `--once` 全部健康，exit 0 |
| 当前站点 smoke | `/`、`/items`、`/reports`、`/ask`、`/eval`、`/ops`、管理页与 sitemap 均 200 |

Web 本轮 `npm audit` 为 0；完整 typecheck/lint/Vitest/build 的重新安装受本机 npm 下载超时
阻断。业务前端源码未修改，release workflow 已被改成只有同提交 Web CI 全绿才允许构建镜像。
Chrome 进程、扩展和 native host 自检均正常，但 Codex 浏览器控制内核无法创建运行资源，
所以本卡不伪称完成了新的人工视觉点击验收。

## 4. 仍需目标服务器/主人权限

1. 轮换 GitHub、DeepSeek、硅基流动、Postgres 与管理令牌；
2. 在两个模型供应商控制台设置真实消费上限；
3. 提供服务器后设置防火墙、Cloudflare DNS、Full (strict) TLS 与源站访问策略；
4. 配置真实 HTTPS webhook 和异机/对象存储备份；
5. 按不可变提交 SHA 部署，再执行公网 smoke、告警失败/恢复通知和目标机恢复复演。

这些都是外部状态与凭据操作，代码仓库无法代替，也未获得 push、打 tag、DNS 或服务器权限。

## 5. 下一张任务卡

服务器就绪后创建“TASK-M5-006 首次生产部署与外部闭环”。若服务器尚未提供，独立 P1
仍是 `TASK-M5-004` 报告订阅与定时投递；它不阻塞网站、AI 动态、每日精选、站内报告或 RAG。

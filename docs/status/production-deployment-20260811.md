# TASK-M5-006 首次生产部署记录

日期：2026-08-11  
状态：**✅ 首次生产闭环完成；v0.1.4 正在 https://aihotradar.online 运行**

## 0B. 2026-08-12 首次生产闭环（当前）

- GitHub `main`、服务器 `production` checkout、`IMAGE_TAG` 与三张业务镜像统一为
  `v0.1.4@6e192a74fbc1f98083dcfc9c44a442959582597d`，服务器工作树干净；
- `web`、`core-api`、`ai-service`、scheduler、pipeline、PostgreSQL、Redis、Caddy、
  monitor 与 backup 共 10 个容器运行；具有健康检查的核心服务均为 healthy；
- `aihotradar.online` 由腾讯云 DNSPod A 记录直连香港源站，Caddy 自动签发与续期
  Let's Encrypt 证书；80 仅跳转 HTTPS，公网只开放 22/80/443；
- 首页、动态、热点、事件、三周期报告、主题、RAG、质量、运行与只读管理页面均返回 200；
  一次真实 RAG 问答总耗时约 7.1 秒，返回 3 条有效引用且未进入 degraded；
- Gmail SMTP 生产实投返回 `smtp_test=sent`；受控 monitor 故障与恢复各发送一次通知，
  `alert_sent=true`、`recovery_sent=true`；报告投递失败仍不阻塞站内发布或采集；
- 生产备份 `ai_hot_radar-20260811T172244Z.dump` 为 104071824 字节，SHA-256 为
  `37201c5882a54cab13e1d0709fb97eb5c7149ec957f06ddf129cc68930aa50c0`；异机副本哈希一致，
  隔离恢复核对为 `140|1873|7098|1456|15|024`；
- 2026-08-12 当前库滚动快照为 `140|105 ACTIVE|1927 content|7269 chunks|1511 stories|V024`。

至此 TASK-M5-006 的首次上线目标关闭。下面 §0、§1–§5 保留的是上线过程中的历史暂停
快照与 fail-closed 证据，不再代表当前运行状态。

## 0. 2026-08-11 23:06 发布与暂停快照

- PR [#3](https://github.com/linruibang19-home/AI-Hot-Radar/pull/3) 的五项 CI 全绿后已合并到
  `main@4c4973575249f7f1a883a36a9cf3532a14fef0a4`；
- 标签 `v0.1.3` 已创建，Release
  [31504670925](https://github.com/linruibang19-home/AI-Hot-Radar/actions/runs/31504670925)
  在同一提交上重复通过 spec、Python、Java、Web 和空库 Flyway 门禁；
- `web`、`ai-service`、`core-api` 三张生产镜像均已发布 `v0.1.3`、`latest` 与
  `sha-4c4973575249f7f1a883a36a9cf3532a14fef0a4`；
- 香港目标机 `production` 已从 `0ae2fa75` 严格 fast-forward 到 `4c497357`，工作树干净，
  精确标签为 `v0.1.3`；目标机可匿名读取 GHCR manifest，因此镜像拉取不依赖聊天中暴露的 PAT；
- 目标机根盘 40 GiB、可用 31 GiB，Docker 29.7.2、Compose 5.4.0；项目容器数仍为 0；
- 域名 `aihotradar.online` 的 A 记录继续指向 `47.242.229.41`；80/443 没有项目监听，
  尚未签发 TLS 证书，公网仍未上线；
- 新版真实 `.env` 预检按设计失败 14 项，全部是外部配置或运维确认；没有为了“先启动”
  降低门禁，也没有使用聊天中出现过的 DeepSeek、SiliconFlow 或 GitHub 密钥；
- 本地 V024 的 102 MiB dump 已完成 SHA/目录校验与隔离恢复，恢复快照为
  `140|1915|7264|1498|15|024`，但生产异机持续备份仍未建立。

在该历史快照时，生产保持停止是正确状态：代码、标签、镜像和服务器 checkout 已经就绪，
但真实模型调用、邮件投递、告警、供应商预算与异机备份尚不能形成安全闭环。

## 0A. 2026-08-12 SMTP 告警收敛

- monitor 已增加 SMTP 故障/恢复告警，可复用报告投递账户并发送到 `ALERT_EMAIL_TO`；
- 原 Slack-compatible HTTPS webhook 保留为可选第二通道；
- preflight 改为要求两类告警目的地至少配置一个，没有降低告警门禁；
- 交付测试、Ruff、结构 fixture 预检和生产 Compose 解析均通过；变更需随下一发布标签进入服务器。

## 1. 已完成

- 香港 Ubuntu 22.04 目标机完成系统更新并重启；
- 安装 Docker Engine 29.7.2 与 Docker Compose 5.4.0，`hello-world` 通过；
- 创建专用 `deploy` 用户和项目专用 SSH 密钥，部署目录为 `/opt/ai-hot-radar`；
- 禁用 SSH 密码和键盘交互认证，root 只允许密钥登录；聊天中出现过的口令未被使用；
- UFW 默认拒绝入站，只允许 22、80、443；2 GiB swap 已启用，`vm.swappiness=10`；
- 外部临时探针验证 80/443 均能穿过云安全组和 UFW，探针随后删除；
- 目标机检出 `codex/rag-quality-gates`，工作树干净并跟踪 GitHub 同名分支；
- 生产 `.env` 已在目标机生成，权限 600；Postgres、内部服务和两级管理令牌均为目标机新生成值，
  未写入 Git、日志或聊天；
- 仓库结构 fixture 在目标机通过 production preflight；真实 `.env` 在外部条件缺失时按设计拒绝启动；
- 三个 `sha-29cb967b2b32e347b5fdaa83edfd962d13abb8e0` 镜像已发布，目标机可读取 manifest。

## 2. 发布记录

| 项目 | 结果 |
|---|---|
| 部署提交 | `29cb967b2b32e347b5fdaa83edfd962d13abb8e0` |
| 分支 | `codex/rag-quality-gates` |
| `v0.1.0` | 被空库门禁拦截；发现 CI 用字典序误排 `V017_1` 与 `V017` |
| 修复 | `.github/workflows/ci.yml` 按 Flyway 版本段排序，并将扩展/基表检查改为真实断言 |
| `v0.1.1` | [Release 31476721634](https://github.com/linruibang19-home/AI-Hot-Radar/actions/runs/31476721634) 全部通过 |
| `v0.1.3` | [Release 31504670925](https://github.com/linruibang19-home/AI-Hot-Radar/actions/runs/31504670925) 全部通过 |
| CI | Web、AI service、Core API、spec、空库 V001–V024 全绿 |
| 当时部署提交 | `4c4973575249f7f1a883a36a9cf3532a14fef0a4`（服务器当时已对齐，尚未启动） |
| ai-service 镜像 | `sha256:6bd7849f85d8fe0f4002122a3f28cabe95b5aff28b506f9b68ff4cbd6e4689b7` |
| core-api 镜像 | `sha256:f69349472e5c22601436d4a1b3d2460b069d0ca360ff54a8368fdf100a2d1645` |
| web 镜像 | `sha256:aa663ee34111c835665c9d81cfb4932df28710281906873adf9891e886f2029d` |

## 3. 当时的 fail-closed 闸门（历史）

目标机在 `v0.1.3` 上执行 `sh infra/scripts/preflight.sh infra/compose/.env`，报告 14 个问题，
归并后只剩以下外部条件：

1. 轮换后的 `LLM_API_KEY`、`EMBEDDING_API_KEY` 和用于 GitHub 数据源限流的专用 token；
2. 生产 SMTP 主机、发件地址、认证/TLS 选择、投递间隔和至少 32 字符的订阅签名密钥；
3. 可实际接收的 SMTP 告警收件地址，或 Slack-compatible HTTPS webhook；
4. DeepSeek / SiliconFlow 控制台消费上限确认；
5. 异机备份目标与持续同步责任确认。

这些值不得通过聊天发送。主人应在自己的供应商控制台创建专用凭据并设置消费上限，随后在
SSH 会话中直接填写目标机的 `infra/compose/.env`；预检全绿前不得运行生产部署脚本。

## 4. 启动后的验收顺序

1. 新域名 A 记录指向目标机；先关闭 CDN 代理直至 Caddy 取得证书；
2. 运行 `infra/scripts/deploy-production.sh`，确认所有容器 healthy；
3. 公网验证首页、AI 动态、精选、日报/周报/月报、`/ask`、`/eval`、`/ops`；
4. 验证公网管理 API 为 404、内部 Postgres/Redis/API 端口不可达；
5. 触发一次受控告警失败与恢复，并实际收到两条通知；
6. 生成首份备份，复制到异机目标，再运行隔离 `restore-verify`；
7. CDN 切为 Full (strict)，复验安全头、真实客户端 IP、RAG 引用和报告发布流程。

## 5. 尚未声明完成的内容

- 尚未启动生产容器或对外提供半配置站点；服务器只有代码与镜像发布态就绪；
- 尚未签发域名证书；
- 尚未验证真实模型调用、采集、RAG、三周期报告和推送；
- 尚未取得真实告警与异机恢复证据，RPO/RTO 仍不能关闭。


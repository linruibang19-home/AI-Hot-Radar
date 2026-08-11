# TASK-M5-006 首次生产部署记录

日期：2026-08-11  
状态：**服务器与发布制品就绪；等待主人提供域名和专用外部凭据后启动业务**

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
| CI | Web、AI service、Core API、spec、空库 V001–V022 全绿 |
| 镜像 | `web`、`ai-service`、`core-api` 均构建并推送成功 |

## 3. 当前 fail-closed 闸门

目标机执行 `sh infra/scripts/preflight.sh infra/compose/.env` 时只报告以下未完成外部条件：

1. 新域名、`https://` 公网地址和 ACME 运维邮箱；
2. 目标机专用、低额度的 LLM、embedding/rerank、GitHub 凭据；
3. 模型供应商控制台消费上限确认；
4. 真实 HTTPS 告警 webhook；
5. 异机备份的目标与责任人确认。

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

- 尚未启动生产容器或对外提供半配置站点；
- 尚未签发域名证书；
- 尚未验证真实模型调用、采集、RAG、三周期报告和推送；
- 尚未取得真实告警与异机恢复证据，RPO/RTO 仍不能关闭。


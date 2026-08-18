# v0.1.19 模型配置可编辑供应商发布（2026-08-18 部署 / 2026-08-19 补记）

## 发布对象

- GitHub 合并提交：`be8601cdd61dbab5ea18cc0b48a929056c7d35fc`（PR #37 功能、PR #38 生产
  compose 修补）；
- Release 标签：`v0.1.19`，Release workflow 5m35s，产出三张
  `sha-be8601cdd61dbab5ea18cc0b48a929056c7d35fc` 镜像；
- 生产地址：<https://aihotradar.online>；
- 目标环境：香港 Ubuntu 22.04.5、2C4G、Docker Compose、Caddy HTTPS。

这次发布让 `/admin/models` 可以直接改生成供应商的地址与 API Key（ADR-0032），并修掉
`robots.txt` 把构建期的 `http://localhost:3000` 发布到线上的问题。不改 RAG 检索策略，也
不改任何既有实体。

## 发布门禁

| 层 | 结果 |
|---|---|
| Python | 通过（含 `test_prod_compose.py` 新增的凭证主密钥断言） |
| Java | Maven JDK 21 通过 |
| Web | typecheck、lint、Vitest、Next production build 通过 |
| 数据库 | Flyway 空库应用至 V027 通过 |
| 规格文档 | `validate_spec.py`、`validate_docs.py` 通过 |

## 数据库变更

V027 建 `generation_provider_config` 单行表，种子值写 `env://LLM_BASE_URL` 占位符。
**该迁移在生产上是 no-op**：应用后生成侧仍逐字段回落到 `LLM_BASE_URL` / `LLM_API_KEY`，
行为与 V026 完全一致。部署后实查：

```
base_url = env://LLM_BASE_URL | key_from_env = t | key_fingerprint = (null) | version = 1
```

## 生产部署

服务器 `/opt/ai-hot-radar` 严格 fast-forward 到 `be8601c`，工作树干净。`.env` 新增
`LLM_CREDENTIAL_MASTER_KEY`（`openssl rand -base64 32`，44 字符 / 解码 32 字节 / 600 /
属主 `deploy`），全程未输出其值。原 `.env` 备份移到 `/root/ahr-env-backups/` —— 放在仓库
内会让部署脚本的干净检出检查失败。

`deploy-production.sh` 以 `deploy` 用户执行，`EXIT=0`，
`deploy OK: sha=be8601cdd61dbab5ea18cc0b48a929056c7d35fc`，smoke 全部通过。

## 部署后验收

| 项 | 结果 |
|---|---|
| `robots.txt` | `Sitemap: https://aihotradar.online/sitemap.xml`（本次要修的问题，已确认） |
| `sitemap.xml` | `<loc>https://aihotradar.online</loc>` |
| 页面 | `/`、`/items`、`/reports`、`/ask`、`/ops`、`/eval`、`/admin/models` 均 200 |
| Flyway | `027 | generation provider credential` |
| 容器 | 10 个服务 Up / healthy |
| 供应商接口 | `credentialStorageReady: true`，`usesEnvironment: true` |
| pipeline | `pipeline pass done in 43.5s: enriched=1 embedded=1 stories=2319` |
| scheduler | `tick claimed=10 ok=10 failed=0 persisted=1` |

`credentialStorageReady: true` 是 PR #38 的验收点：主密钥确实到达了 core-api，保存按钮
是可用的而不是返回 503。

## 过程中发现并修掉的问题

**生产 compose 缺少 `LLM_CREDENTIAL_MASTER_KEY`（打标签前发现）。** PR #37 只把该变量加进
了本地 compose。所有门禁都是绿的，但上线后 core-api 与 ai-service 会回答「本站不能保存
密钥」、保存按钮 503，而 pipeline 会正常启动然后每一轮富化静默失败 —— 一个看起来存在、
实际不工作的功能。PR #38 在三个服务上都声明该变量，preflight 增加长度检查，并补了一条
读取生产 compose 的静态断言（`test_every_generation_worker_can_decrypt_a_stored_credential`），
即本来就该拦下 PR #37 的那条。

**第一次部署以 root 执行失败（EXIT=128）。** 仓库属主是 `deploy`，触发 git 的
dubious ownership 保护。失败发生在 `docker compose pull` 之前，生产未被改动。改以
`deploy` 用户重跑后 EXIT=0。没有为 root 添加 `safe.directory` 例外：那会让 root 建出的
文件破坏后续由 `deploy` 执行的部署。

**本地构建产物目录导致两次生产形态的故障。**
`apps/core-api/src/main/resources/db/migration/` 由构建期 `cp` 填充且被 gitignore，
`git checkout` 不会清理它。结果是已回退的分支迁移被重新应用，以及
`Found more than one migration with version 027` / `Migration checksum mismatch`。
两次都通过删除该目录并重新清库解决。仅影响本地。

## 遗留

- 主密钥必须离机备份。丢失后所有已入库密钥不可解，只能重置回环境变量重填；
- 部署脚本收尾提示的三项运维动作（核对备份日志、跑 restore-verify、把源站入口收紧到
  Cloudflare 段）尚未执行；
- `main` 分支未开启保护与必需状态检查。

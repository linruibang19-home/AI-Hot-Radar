# 换服务器：交接参数（2026-09-17 实查）

> 这份是给**新会话窗口**的冷启动输入：不解释设计，只给执行需要的确切值。
> 操作步骤在 [`../design/server-migration-runbook.md`](../design/server-migration-runbook.md)，
> 这份只回答「当前是什么状态、下一步该干什么」。
>
> 表里所有数字都是 2026-09-17 12:37 UTC 连上服务器实测的，不是记忆。

---

## 1. 一句话现状

线上正常运行，**没有故障**。唯一待办是旧机即将到期，要迁到一台新的同配置香港机；
迁移手册已经写好并合进 main，**尚未执行**。

---

## 2. 旧机（待迁出）

| 项 | 值 |
|---|---|
| IP | `47.242.229.41` |
| ASN | AS45102（阿里云香港）—— **七个信源被这个网段的信誉拦掉，见 §6** |
| SSH | `ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@47.242.229.41` |
| 认证方式 | **仅公钥**，`PasswordAuthentication no`（密码登录不可用） |
| 项目路径 | `/opt/ai-hot-radar`（属主 `deploy`，**不要用 root 操作**） |
| 磁盘 | 40 G 中已用 17 G（**46%**） |
| 容器 | 10 个全部在运行，`ai-service` / `core-api` / `postgres` / `redis` / `web` 报 healthy |

## 3. 线上版本与代码位置

| 项 | 值 |
|---|---|
| 生产 tag | **v0.1.27** |
| 生产镜像 | `IMAGE_TAG=sha-a734ab80cd28e41616430c09438dd33dbc844f4e` |
| 服务器 git HEAD | `a734ab80cd28e41616430c09438dd33dbc844f4e`（与 IMAGE_TAG 一致 ✅） |
| 本地/远端 main | `24d55b2cda225f6b13fa5cd10e887e54cbde6cc4` |
| 仓库 | `https://github.com/linruibang19-home/AI-Hot-Radar` |

> ⚠ **main 比生产超前两个提交**，都还没上线：
> - `d1dbb72` web 安全升级（next 15.5.25 等，**这是要不要先发版的关键**，见 §8）
> - `24d55b2` 迁移手册文档
>
> 这直接决定迁移当天会不会卡住：新机 `git clone` 拿到的是 main（`24d55b2`），
> 而 `.env` 里的 `IMAGE_TAG` 指向 `a734ab8`，`deploy-production.sh` 的自检
> `IMAGE_TAG == sha-$(git rev-parse HEAD)` 会**直接退出**。手册第 3 节有处理方法。

## 4. 数据（要迁的就是这些）

| 项 | 值 |
|---|---|
| `content_item` | **7026** |
| `content_chunk`（`is_active`） | **38804** |
| `source` | **151** |
| `report` | **57** |
| 数据库大小 | **1642 MB** |

**信源运行状态**（列名是 `runtime_state`，**不是** `status`）：

| ACTIVE | CONFIGURED | QUARANTINED | METADATA_ONLY | PROBING | RATE_LIMITED |
|---:|---:|---:|---:|---:|---:|
| 129 | 11 | 6 | 2 | 2 | 1 |

## 5. 备份

| 项 | 值 |
|---|---|
| 服务器路径 | `/opt/ai-hot-radar/infra/compose/backups/`（bind mount，容器内是 `/backups`） |
| 目录总量 | 4.4 G |
| 最新一份 | `ai_hot_radar-20260917T113509Z.dump`，**599 MB** |
| 保留策略 | `BACKUP_KEEP_DAYS=7` |
| 手动触发 | `docker compose ... run --rm -e BACKUP_RUN_ONCE=true backup`（常驻容器是 sleep 循环，直接 run 会挂住） |
| 校验方式 | `restore-verify` 服务（比对 Flyway 版本 + 五张表行数） |
| 异地副本 | 本机 `D:\Backups\AI Hot Radar`，Windows 计划任务 `AI Hot Radar - Pull Production Backup` 每日 scp |

## 6. 域名与网络

| 项 | 值 |
|---|---|
| 域名 | `aihotradar.online` |
| A 记录 | → `47.242.229.41` |
| **TTL** | **600 秒**（切换窗口就是这 10 分钟） |
| CDN | **没有**（`Via: 1.1 Caddy`，A 记录直指源站；旧文档说的 Cloudflare 不存在） |
| 证书 | Caddy 自动申请，**不用迁**，但要求 DNS 先指过去才签得到 |
| 公网状态 | 首页 200 ✅ |

**被 ASN 拦掉的七个信源**：三个 OpenAI 文档站、`openai-news`、`xai-news`、
`venturebeat-ai`、`bair-blog`。原因是 AS45102 的网段信誉，**不是地理位置也不是请求量**
（`xai-news` 日均 4 次请求照样被封）。换厂商时值得先花两分钟 `curl` 测，同厂商换 IP 无效。

## 7. 已知且可接受的告警

`/health/sources` 返回 **503**，内容是：

| 信源 | 优先级 | 成功轮询 | 已停滞 |
|---|---|---:|---:|
| `openai-news` | P0 | 3677 次 | 46.8 天 |
| `venturebeat-ai` | P1 | 642 次 | 46.8 天 |

**这是功能正常的表现，不是故障**——它正确报出了「轮询成功但从未产出」。
根因就是 §6 的 ASN 封锁。迁移后如果变成 200，要先分辨是真恢复了还是还没轮到第一次采集。

---

## 8. 下一步：一个待拍板的决定

安全修复在 main 但没上线（§3）。两条路：

**A. 先发版部署到旧机，再迁移**（建议）
`.env` 的 `IMAGE_TAG` 与 main HEAD 对齐，迁移当天**直接绕过** §3 那个自检坑。
代价是多一次发布。

**B. 先迁移，迁完再升级**
迁移当天需要按手册第 3 节把新机 `git checkout` 到 `a734ab8`。
好处是迁移与升级不混在一起，出问题好定位。

> 两条路手册都写了。选 A 的话，发布流程是打 `v0.1.28` 标签触发 GitHub Actions 构建镜像，
> 然后在服务器上更新 `.env` 的 `IMAGE_TAG` 并跑 `deploy-production.sh`。

---

## 9. 待办（与迁移无关，但别丢）

- 19 道模型标注的黄金题（`annotation.method: model_assisted`、`reviewed_by: null`）**未经人工复核**，在此之前不能对新集设阈值
- 黄金集计划第 3 步：双轨评测 `rag-eval --set regression|fresh`；第 4 步：轮换规则写进 ADR
- `anthropic-api-release-notes` 仍只有 1 条，原因未知
- 488/489 条 `static_listing_to_article` 缺 `published_at`；直接回填会把 2023-11-03 写满所有 Anthropic 页面，**需要先做站点级常量检测**
- uvicorn 的访问日志（`/health/live`）淹没了 ai-service 自己的 JSON 日志
- `numeric_audit` 占约 24% 延迟，从未被评估过
- RAG-GOLD-088：v4-flash 编造了「Apache 2.0 许可证」——生成侧 groundedness 问题
- `sync-sources` 不会把已移除的信源置为 disabled
- 仓库没有 `LICENSE` 文件，README 写的是「默认保留所有权利」

## 10. 两件安全待办（请本人处理）

1. **轮换服务器密码** —— 它曾出现在一张截图里。（注：该机 `PasswordAuthentication no`，所以不影响 SSH，但仍应轮换）
2. **轮换硅基流动 API Key** —— 我曾因为一条 `sed` 掩码失效而完整打印过它。

---

## 11. 长期约定（新窗口请遵守）

- 提交**不要**带 Claude 署名或 `Co-Authored-By` trailer，作者一律 `LRB <linruibang19@gmail.com>`
- Java 侧用 **Maven**，不用 Gradle
- 每完成一步汇报进度，并写进 `docs/`
- 不要以 root 操作 `/opt/ai-hot-radar`（属主是 `deploy`）
- `LLM_CREDENTIAL_MASTER_KEY` 必须有异地备份，且**永远不要打印**

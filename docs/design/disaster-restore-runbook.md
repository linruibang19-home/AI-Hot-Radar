# 灾难恢复：从零重建线上

> 和 [`server-migration-runbook.md`](server-migration-runbook.md) 的区别：那份假设旧机还活着，
> 可以从容切换；**这份假设旧机已经没了**。
>
> 触发场景：2026-09-18 旧机（`47.242.229.41`）租期到期消失，SSH/HTTP 全部不可达，
> 只剩本机 `D:\Backups\AI Hot Radar` 的转储。

---

## 0. 手上有什么、缺什么

| | 状态 |
|---|---|
| 数据库转储 | ✅ `ai_hot_radar-20260916T113254Z.dump`，581 MB，SHA-256 已校验 |
| 嵌入向量 | ✅ 在转储里（已抽样确认是真实浮点值，不是 NULL） |
| 代码 | ✅ GitHub `main` = `d7568de` |
| 镜像 | ✅ GHCR 已有 `sha-d7568def1bb6b3253d9317aed02ef6c586dac5f7`（v0.1.28） |
| 域名 | ✅ `aihotradar.online` 还在，A 记录指向已死的旧 IP，TTL 600s |
| **`.env`** | ❌ **没有备份，必须重建**（见 §2） |
| TLS 证书 | ❌ 随旧机消失，但 Caddy 会重新申请 |

**转储里的数据**（2026-09-16 11:32 UTC 快照）：

| content_item | content_chunk | source | story | report | Flyway |
|---:|---:|---:|---:|---:|---:|
| 6851 | 37244（is_active 37164） | 151 | 3627 | 56 | V027 |

> 初版这里写 38804，那是 **2026-09-17 线上**的 `is_active` 计数，被错抄进了转储的表。
> 转储是 9/16 的。2026-09-19 实际恢复后核对为 37244。拿错数字对账会把一次成功的
> 恢复误判成丢数据。

---

## 1. 新机的前置条件（只有机主能做）

这一步在服务商控制台完成，不经过网络，所以机器不通也能做：

1. 确认实例 **Running**
2. 安全组/防火墙放行 **22 / 80 / 443**
3. 装部署公钥：

```bash
mkdir -p ~/.ssh && echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMipq4slEEqjNsHaaZG46FXSsHXws4l8aB4L9EdwYOs9 ai-hot-radar-deploy-20260811' >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
```

确认可达之后再往下：

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 -o BatchMode=yes deploy@<新IP> 'echo OK; df -h /; free -m'
```

**磁盘要 ≥40 G**（数据库 1.6 G + 备份 4.4 G + 三张镜像约 2 G + 系统与 Docker 开销）。
内存 4 G 刚好：compose 常驻上限合计 3.17 G，建议加 2 G swap：

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## 2. 重建 `.env`（这一步最容易出错）

68 个键，但**只有 4 个需要从外部重新获取**，其余要么生成、要么照抄默认值。

### 2.1 必须去控制台重新取的（4 个）

| 键 | 从哪来 |
|---|---|
| `LLM_API_KEY` | DeepSeek 控制台 |
| `EMBEDDING_API_KEY` | 硅基流动控制台（重排也用这把） |
| `GITHUB_TOKEN` | GitHub → Settings → Developer settings，只要 `public_repo` 读权限 |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | 邮件服务商 |

> 旧的那几把随机器一起没了，**本来也该轮换**（硅基流动那把曾被误打印）。

### 2.2 本机生成的（5 个，各跑一次）

```bash
openssl rand -hex 32   # INTERNAL_SERVICE_TOKEN
```

```bash
openssl rand -hex 32   # AHR_ADMIN_BOOTSTRAP_TOKEN（运维用，OPERATOR）
```

```bash
openssl rand -hex 32   # AHR_ADMIN_VIEWER_TOKEN（web 容器用，只读）
```

```bash
openssl rand -hex 32   # AHR_SUBSCRIPTION_TOKEN_SECRET
```

```bash
openssl rand -base64 32   # LLM_CREDENTIAL_MASTER_KEY —— 必须 base64 解码后是 32 字节
```

> **管理令牌短于 32 字符 core-api 会拒绝启动**（不是告警），因为存储用的是不加盐 SHA-256。
>
> `LLM_CREDENTIAL_MASTER_KEY` 换一把新的**没有副作用**：转储里
> `generation_provider_config.api_key_ciphertext` 是 NULL，
> 说明生产从未把密钥加密入库，一直走的是 `LLM_API_KEY` 环境变量。
> （2026-09-18 从转储实查确认。）

`POSTGRES_PASSWORD` 也重新生成一个即可 —— 恢复用 `--no-owner`，不依赖旧口令。

### 2.3 本次部署相关

```
IMAGE_TAG=sha-d7568def1bb6b3253d9317aed02ef6c586dac5f7
IMAGE_REPO=ghcr.io/linruibang19-home/ai-hot-radar
SITE_DOMAIN=aihotradar.online
PUBLIC_BASE_URL=https://aihotradar.online
APP_ENV=production
ACME_EMAIL=<你的邮箱，留空则证书续期失败时无人收到通知>
PROVIDER_BUDGET_CAP_CONFIRMED=true
BACKUP_OFFSITE_CONFIRMED=true
```

其余键照 `.env.example` 的默认值填。填完锁权限并预检：

```bash
chmod 600 infra/compose/.env && sh infra/scripts/preflight.sh infra/compose/.env
```

---

## 3. 部署代码与恢复数据

```bash
git clone https://github.com/linruibang19-home/AI-Hot-Radar.git /opt/ai-hot-radar && cd /opt/ai-hot-radar && git checkout d7568def1bb6b3253d9317aed02ef6c586dac5f7
```

> `deploy-production.sh` 自检 `IMAGE_TAG == sha-$(git rev-parse HEAD)`。
> `d7568de` 就是 main 的 HEAD，所以**直接 clone 不切换也可以**，这里写出来只是为了明确。

**先只起数据库**，不要 `up -d` 全部 —— core-api 会在空库上跑 Flyway，和 `pg_restore` 撞车：

```bash
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml up -d postgres && sleep 20
```

把转储传上去（`backups/` 是 bind mount，容器内即 `/backups`）：

```bash
scp -i ~/.ssh/ai_hot_radar_deploy_ed25519 "D:/Backups/AI Hot Radar/ai_hot_radar-20260916T113254Z.dump" deploy@<新IP>:/opt/ai-hot-radar/infra/compose/backups/
```

```bash
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml exec -T postgres pg_restore -U ai_hot_radar -d ai_hot_radar --no-owner --exit-on-error /backups/ai_hot_radar-20260916T113254Z.dump
```

> `--exit-on-error` 不能省：默认是**报错继续**，最后退出 0，
> 于是缺表的库看起来像恢复成功。
>
> 空库首次恢复不需要 `--clean --if-exists`。

核对（必须和下表完全一致）：

```bash
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml exec -T postgres psql -U ai_hot_radar -d ai_hot_radar -c "SELECT (SELECT count(*) FROM content_item) AS 内容, (SELECT count(*) FROM content_chunk) AS 分块, (SELECT count(*) FROM source) AS 信源, (SELECT count(*) FROM story) AS 故事, (SELECT count(*) FROM report) AS 报告, (SELECT max(version) FROM flyway_schema_history WHERE success) AS 迁移;"
```

| 内容 | 分块 | 信源 | 故事 | 报告 | 迁移 |
|---:|---:|---:|---:|---:|---:|
| 6851 | 37244 | 151 | 3627 | 56 | 027 |

全部 37244 个分块的 `embedding` 均非 NULL。

---

## 4. 切 DNS，再起全部容器

**顺序不能反**：Caddy 要 DNS 已经指过来才签得到证书（HTTP-01 挑战）。

1. A 记录 `aihotradar.online` → `<新IP>`
2. 等 **600 秒** TTL
3. 确认：`nslookup aihotradar.online 8.8.8.8`
4. 起全部：

```bash
cd /opt/ai-hot-radar && sh infra/scripts/deploy-production.sh
```

```bash
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml logs caddy --tail 30 | grep -iE "certificate obtained|error"
```

> 这次和迁移不同：**旧机已经死了，没有"切早了会中断"的顾虑**，DNS 可以第一时间就改。

---

## 5. 验证

```bash
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml ps
```

- 10 个容器，`ai-service` / `core-api` / `postgres` / `redis` / `web` 报 healthy
- core-api 日志应有两条 `registered admin credential`：`'bootstrap' as OPERATOR` 与 `'web' as VIEWER`；
  **只有一条说明少配了一个管理令牌，信源后台会是空的**
- 浏览器打开 `https://aihotradar.online`，证书有效、首页有内容
- 等一个采集周期（scheduler 每 120s），确认 `last_success_at` 在推进

**采集会自己补上缺口**：游标停在 2026-09-16，下一轮会重新发现这期间发布的内容。
永久丢失的只有 9/16–恢复日之间的 RAG 提问记录。

---

## 6. 收尾

```powershell
# 本机计划任务硬编码了旧 IP，不改的话异地备份静默停止
$t = Get-ScheduledTask -TaskName "AI Hot Radar - Pull Production Backup"; $a = $t.Actions[0]; $a.Arguments = $a.Arguments -replace '47\.242\.229\.41', '<新IP>'; Set-ScheduledTask -TaskName $t.TaskName -Action $a
```

```powershell
# 新机指纹必须写进 known_hosts：任务带 BatchMode=yes + StrictHostKeyChecking=yes，
# 遇到未知主机不会提示，直接失败退出，备份就这么无声停掉
ssh-keyscan -t ed25519 <新IP> | Out-File -Append -Encoding ascii "$env:USERPROFILE\.ssh\known_hosts"
```

```powershell
ssh-keygen -R 47.242.229.41
```

还要做：

- 把 `check.sh` 重建到新机 `~`（旧机的那份随机器没了）
- 更新 `docs/status/current/production-baseline.md`
- **这次务必先做 `.env` 异地备份**——这次的教训就是它没备份：

```bash
scp -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@<新IP>:/opt/ai-hot-radar/infra/compose/.env "D:/Backups/AI Hot Radar/env-backup-$(date +%Y%m%d).txt"
```

---

## 7. 这次事故的教训

| 教训 | 已改 |
|---|---|
| **`.env` 从未异地备份** —— 迁移手册第 1 节第 ① 条写了，但没执行 | 本文档 §6 列为强制收尾项 |
| 每日转储只在服务器本地生成，异地拷贝滞后一天 | 最新一份丢了约 1 天数据；可接受，但应缩短间隔 |
| `LLM_CREDENTIAL_MASTER_KEY` 被反复描述为"丢了就没救" | **实查证伪**：生产从未加密入库，密文列是 NULL |
| 租用机器到期即消失，且不可续 | 新机到期前 ≥3 天执行本文档 §6 的备份项 |

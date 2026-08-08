# M5 首次部署清单：会踩的坑，按会踩到的顺序

上级：`docs/design/m5-deployment.md`（方案与选型）、`AHR-QSO-700` §4
状态：**清单已核对，部署待执行**

`m5-deployment.md` 说的是「怎么选、为什么这么选」。这份说的是
**你照着做的时候，第几步会出问题**。每一条要么是我在审查产物时实际发现并已修的，
要么是配置组合决定的、必然会遇到的。

---

## 0. 先做这件事，别等最后

**轮换全部密钥。** GitHub PAT、DeepSeek、硅基流动、Postgres 口令——
它们出现在开发会话记录里。

这条排第一不是仪式感：**下面每一步都要把密钥写进服务器上的 `.env`**，
先轮换，就只需要写一次。

顺便生成两个新的管理端凭据（V016 起需要）：

```bash
openssl rand -hex 32   # AHR_ADMIN_BOOTSTRAP_TOKEN，运维自己用（OPERATOR）
```

```bash
openssl rand -hex 32   # AHR_ADMIN_VIEWER_TOKEN，web 容器用（只读）
```

短于 32 字符 core-api 会**拒绝启动**（不是告警）——因为存储用的是不加盐的
SHA-256，那个选择只在令牌高熵时才成立。

---

## 1. `.env` 的位置是错得最快的一步

生产 compose 读的是 **`infra/compose/.env`**，不是仓库根目录的 `.env`。

原因写在文件里：Compose 解析 `${VAR}` 时只看**compose 文件旁边**的 `.env`，
从来不看 `env_file:` 指的那个。把密钥放在仓库根目录，`${POSTGRES_PASSWORD}`
会静默解析成默认值。

```bash
cp .env.example infra/compose/.env   # 然后填真值
```

`env_file` 标了 `required: true`，所以文件不存在会**直接报错**而不是带着空值启动。
这是故意的。

必填（缺一个就启动失败，用的是 `${VAR:?...}` 语法）：
`POSTGRES_PASSWORD` · `INTERNAL_SERVICE_TOKEN` · `AHR_ADMIN_BOOTSTRAP_TOKEN` ·
`AHR_ADMIN_VIEWER_TOKEN` · `PUBLIC_BASE_URL` · `SITE_DOMAIN`

---

## 2. 服务器上要放**整个仓库**，不是只放 compose 文件

`ai-service` / `scheduler` / `pipeline` 三个服务挂了 `../../config`（信源注册表、
分类词表），`ai-service` 还挂了 `../../data`。只 `scp` 一个 compose 文件过去，
容器会因为挂载路径不存在而起不来。

```bash
git clone https://github.com/linruibang19-home/AI-Hot-Radar.git ai-hot-radar
```

**别在服务器上 `git clean -xdf`**：备份落在 `infra/compose/backups/`，
那是仓库目录内、且被 `.gitignore` 忽略——`git clean -x` 会连备份一起删掉。

---

## 3. 镜像：两个会让首次拉取失败的坑（已修）

**① 标签格式。** workflow 用 `type=sha,format=long`，产出的是 `sha-<40 位十六进制>`，
**不是**裸 commit sha。用裸 sha 部署，`pull` 什么也拉不到，`up -d` 会**安安静静**
继续跑本机已有的旧镜像——最难发现的那种失败。

**② `latest` 以前不会被产出。** 原来写的是
`type=raw,value=latest,enable={{is_default_branch}}`，而这个 workflow 由 `v*` **标签**触发，
标签 ref 不是分支，所以那次发布**不会产出 `latest`**——而 compose 的默认值恰好是
`latest`。首次 `up -d` 必然拉取失败。已改成无条件产出。

**③ GHCR 默认私有。** 服务器第一次拉取前要登录一次：

```bash
echo <PAT with read:packages> | docker login ghcr.io -u linruibang19-home --password-stdin
```

---

## 4. Cloudflare 橙云会挡住证书签发

**这是最容易卡住半小时的一步。**

Caddy 要向 Let's Encrypt 证明你控制这个域名。如果 A 记录一开始就是**橙云（代理）**，
Cloudflare 会自己终止 TLS，源站拿不到正常的挑战——TLS-ALPN 挑战直接失败，
HTTP 挑战也会被 "Always Use HTTPS" 的跳转打断。

**正确顺序：**

1. A 记录先设成**灰云（DNS only）**，指向服务器 IP；
2. `docker compose up -d`，等 Caddy 拿到证书（`docker compose logs caddy` 看到
   `certificate obtained successfully`）；
3. 再切成**橙云（Proxied）**；
4. SSL/TLS 模式设 **Full (strict)**。

**Flexible 千万别选**：那样 Cloudflare→源站这一跳是明文，而访问者看到的还是小锁——
这是最像成功的一种失败。

`ACME_EMAIL` 留空是允许的，但那样证书续期出问题时**没有人会收到通知**。填上。

---

## 5. 内存：已修，但要知道为什么

原来生产 compose **一个内存上限都没有**。九个容器实测合计约 1.0 GB
（core-api 363 MB · postgres 300 MB · scheduler 154 MB · 其余都在 60 MB 以下），
听起来 4 GB 绰绰有余——**但 core-api 的 JVM 用的是 `-XX:MaxRAMPercentage=75`，
而容器没有上限时，这个百分比是按宿主机算的**：4 GB 机器上一个 JVM 就敢要 3 GB。

现在每个服务都有上限，合计 3.0 GB，给系统留 1 GB：

| | 上限 | 实测 |
|---|---:|---:|
| postgres | 640m | 300m |
| core-api | 512m | 363m |
| ai-service | 448m | 53m |
| scheduler / pipeline / web | 320m ×3 | 154 / 46 / 54m |
| redis | 192m | 8m |
| caddy / backup | 128m / 192m | <20m |

Redis 另外加了 `--maxmemory 128mb --maxmemory-policy allkeys-lru`。
ADR-005 把 Redis 限定为缓存/限流/短锁，**没有一样是真相来源**，所以内存压力下淘汰是
正确行为；不设 `maxmemory` 的话，答案缓存会一直涨到撞容器上限被 OOM kill——
把一次缓存未命中变成一次重启。

**建议加 2 GB swap**（轻量服务器默认通常没有）：

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

---

## 6. 首次启动的顺序与验证

```bash
cd ai-hot-radar && docker compose -f infra/compose/docker-compose.prod.yml up -d
```

Flyway 在 core-api 启动时把 **V001–V016** 一次性建完（空库首次会跑十几秒）。
镜像里已经带了迁移文件——core-api 的 Dockerfile 用仓库根做 build context 就是为了这个。

按顺序验证：

```bash
docker compose -f infra/compose/docker-compose.prod.yml logs core-api | grep -i "Successfully applied"
```

```bash
docker compose -f infra/compose/docker-compose.prod.yml logs core-api | grep "registered admin credential"
```

应当看到两条：`'bootstrap' as OPERATOR` 与 `'web' as VIEWER`。
只看到一条，说明有一个令牌没配上，信源后台会是空的。

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://<域名>/api/v1/admin/sources
```

**必须是 401。** 返回 200 说明鉴权没生效，立刻停。

---

## 7. 花钱的闸门（应用层限流不是闸门）

`/ask` 有每 IP 限流（3/分、20/天），但 `caller_id` 读的是 `X-Forwarded-For` 首段，
代码注释里自己写了「**可伪造，而且这没关系**」——它防的是顺手薅，不是攻击者。

真正的闸门只有一个：**去 DeepSeek 和硅基流动的控制台设消费上限。**

另外注意：Cloudflare 只在流量经过它时才有用。**如果源站 IP 直接可达**，
任何人都能绕过 Cloudflare 直连并自带 `X-Forwarded-For`，限流形同虚设。
可选加固——把源站防火墙限制为只接受 Cloudflare 的 IP 段。

---

## 8. 备份：没演练过的备份不算备份

`backup` 容器每 24 小时 `pg_dump -Fc` 一次，保留 7 天，落在
`infra/compose/backups/`。它先写 `.partial` 再改名，所以半截的转储不会伪装成好的。

**上线后 48 小时内做一次真的恢复演练**：

```bash
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  pg_restore -U $POSTGRES_USER -d postgres --create --clean /backups/<文件名>.dump
```

两个已知局限，如实记着：
- 备份和数据库**在同一块盘上**。磁盘挂了就都没了。真要防，得往对象存储送一份。
- 保留 7 天意味着**第 8 天才发现的数据损坏无法回滚**。

---

## 9. 部署后的收尾

- [ ] `/eval`、`/ops`、`/ask` 三个页面在公网打得开（这是作品最值得看的部分）
- [ ] `/admin/sources` 能列出信源（说明 VIEWER 凭据配对了）
- [ ] `sitemap.xml` 里是真域名而不是 localhost（靠 `PUBLIC_BASE_URL`）
- [ ] scheduler 日志里能看到 `tick claimed=… ok=…`
- [ ] 隔天回来看 `docker compose logs backup`，确认 `backup ok:`

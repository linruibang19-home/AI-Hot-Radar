# M5 首次部署清单：会踩的坑，按会踩到的顺序

上级：`docs/design/m5-deployment.md`（方案与选型）、`AHR-QSO-700` §4
状态：**本地上线门禁与恢复演练已通过；目标服务器部署待执行**

`m5-deployment.md` 说的是「怎么选、为什么这么选」。这份说的是
**你照着做的时候，第几步会出问题**。每一条要么是我在审查产物时实际发现并已修的，
要么是配置组合决定的、必然会遇到的。

---

## 1. 先做这件事，别等最后

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

## 2. 如果机器**不在你自己的账号下**（租用/代开）

淘宝上「下单后发 SSH 给你」的机器，是开在卖家账号下的。你有 SSH，他有控制台——
他能重置 root 密码、给磁盘打快照、到期不续。这不是说他会，是说**你无法排除**。

而你要往这台机器的 `.env` 里写 DeepSeek Key、硅基流动 Key、Postgres 口令和两个
管理端令牌，**其中两个能直接花钱**。所以按「假设它最终会泄露」来准备，代价很小：

1. **先去两个 provider 控制台设消费上限。** 这是唯一真闸门，无论机器归谁都要做。
2. **给这台机器单独申请一套 API Key**，不要复用本地开发那套——要撤时撤它，不影响自己。
3. **管理端令牌单独生成**（`openssl rand -hex 32` 两次），同理。
4. 到期不续时，**主动吊销**那套 Key，而不是等它自己失效。

下单前还要问清楚五句，第 3 句问不清楚可能白装一天：

1. 是**香港/新加坡节点**吗？（拿成大陆节点就要备案，整条路线不同）
2. 给 **root 或 sudo** 吗？（装 Docker 要）
3. **80 / 443 默认放行吗？还是要你在安全组里帮我开？**
   安全组在卖家控制台，SSH 进去改不了；这两个端口不通，域名 + HTTPS 整套都上不了。
4. 到期续费**还是同一台机器、同一个 IP** 吗？（换 IP 要重配 DNS，换机器数据全丢）
5. 有没有快照或备份？

**备案与否由节点决定，不由这一节决定**：香港/新加坡不需要备案；
真要用大陆节点，先读 §7。

---

## 3. 先把镜像发出来，否则第一条命令就失败

生产 compose 是 **`pull` 不是 `build`**（2 GB 机器上 `next build` 和 Maven 编译会 OOM，
所以镜像在 GitHub Actions 里构建）。而 `release.yml` 只由 **`v*` 标签**或手动触发，
**在你打第一个标签之前，GHCR 上一个镜像都没有**——服务器上 `docker compose pull`
会直接失败，且报的是「找不到镜像」而不是「你还没发布」。

在本地做，不在服务器上做。发布 workflow 会先复用完整 CI，只有同一提交的
Spec/Python/Java/空库迁移/Web 全绿才构建镜像：

```bash
git checkout main && git merge --no-ff <已通过 CI 的发布分支>
```

```bash
git push origin main && git tag v0.1.0 && git push origin v0.1.0
```

然后去 GitHub Actions 看 verify 与三个 build job（web / ai-service / core-api）**全绿**再往下走。
三个镜像各约 300–600 MB，构建加推送通常十几分钟。

**镜像默认是私有的。** 两条路选一条：

- 去仓库 → Packages → 每个包 → Package settings → 改成 Public（服务器就不用登录）；
- 或者服务器上登录一次：

```bash
echo <PAT with read:packages> | docker login ghcr.io -u linruibang19-home --password-stdin
```

---

## 4. `.env` 的位置是错得最快的一步

生产预检默认读 **`infra/compose/.env`**，不是仓库根目录的 `.env`；也可以把显式路径
传给 `preflight.sh` / `deploy-production.sh`，脚本会同时把它传给 Compose，避免两个配置源漂移。

原因写在文件里：Compose 解析 `${VAR}` 时只看**compose 文件旁边**的 `.env`，
从来不看 `env_file:` 指的那个。把密钥放在仓库根目录，`${POSTGRES_PASSWORD}`
会静默解析成默认值。

```bash
cp .env.example infra/compose/.env   # 然后填真值
```

`env_file` 标了 `required: true`，所以文件不存在会**直接报错**而不是带着空值启动。
这是故意的。

填完后先锁权限并预检；不要把 `preflight.env.example` 当生产配置，它只用于结构测试：

```bash
chmod 600 infra/compose/.env
sh infra/scripts/preflight.sh infra/compose/.env
```

预检会拒绝：可变镜像标签、localhost 公网地址、短/相同管理令牌、非 HTTPS 告警地址、
未确认的供应商消费上限或异机备份责任，以及 Linux 上权限不是 600/400 的密钥文件。

---

## 5. 服务器上要放**整个仓库**，不是只放 compose 文件

`ai-service` / `scheduler` / `pipeline` 三个服务挂了 `../../config`（信源注册表、
分类词表），`ai-service` 还挂了 `../../data`。只 `scp` 一个 compose 文件过去，
容器会因为挂载路径不存在而起不来。

```bash
git clone https://github.com/linruibang19-home/AI-Hot-Radar.git ai-hot-radar
```

**装 Docker 的命令取决于镜像**。清单原本假设 Ubuntu 22.04；阿里云轻量默认可能给
Alibaba Cloud Linux（RHEL 系，用 `dnf` 不是 `apt`），官方脚本不一定认这个发行版：

```bash
# Ubuntu / Debian
curl -fsSL https://get.docker.com | sh && systemctl enable --now docker
```

```bash
# Alibaba Cloud Linux 3 / 4（RHEL 系）
sudo dnf -y install docker docker-cli docker-compose-plugin
```

Alibaba Cloud Linux 上更稳妥的是走阿里云自己的 docker-ce 源；装完务必确认
`docker compose version` 有输出——**compose v2 是插件，不随 docker 一起装**，
而本项目的所有命令都是 `docker compose` 而不是 `docker-compose`。

**别在服务器上 `git clean -xdf`**：备份落在 `infra/compose/backups/`，
那是仓库目录内、且被 `.gitignore` 忽略——`git clean -x` 会连备份一起删掉。

---

## 6. 镜像：两个会让首次拉取失败的坑（已修）

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

## 7. 如果买的是**中国大陆节点**，先停下

`m5-deployment.md` §1 选香港/新加坡不是为了省钱，是为了去掉一个不由你控制的阻塞项。
大陆节点有一条硬约束：

> **未完成 ICP 备案的大陆服务器，80 / 443 端口是被封的。**

不是慢，是**网站根本打不开**。备案通常 1–3 周，期间这台机器只能 SSH 进去自己看。
所以在大陆节点上，正确顺序是「先备案、再部署」，而不是这份清单的顺序。

另外三件事会一起变：

- **备案要求账号实名，且必须是你本人。** 如果服务器是通过第三方代购、挂在别人的
  阿里云账号下，你**备不了案**，而且对这台机器没有最终控制权。
- **Cloudflare 橙云与备案冲突。** 备案核验通常要求域名解析到已备案的那个 IP，
  而橙云会把源站藏在 Cloudflare 后面。大陆节点基本要放弃 Cloudflare 代理，
  §8 那套「灰云拿证再切橙云」的流程也就不适用。
- **域名后缀要在工信部核准列表内**才可能备案。`.online` 是否在列请以
  阿里云备案系统的实际校验为准——**不要凭印象判断**，它决定这条路走不走得通。

## 8. Cloudflare 橙云会挡住证书签发

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

## 9. 内存：已修，但要知道为什么

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

## 10. 首次启动的顺序与验证

```bash
cd ai-hot-radar && sh infra/scripts/deploy-production.sh infra/compose/.env
```

部署脚本先要求干净工作树和 `IMAGE_TAG=sha-<当前 HEAD>`，再执行 preflight、pull、
`up -d --wait` 与公网 smoke。Flyway 在 core-api 启动时把 **V001–V024**（含 V017.1）
一次性建完（空库首次会跑十几秒）。
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

**公网必须是 404。** Caddy 只反代 Next.js，内部 Java 管理 API 没有公网路由；返回 401
反而说明内部管理面被暴露。站内 `/admin/sources` 由 VIEWER 令牌在服务器侧读取，页面应为 200。

---

## 11. 花钱的闸门（应用层限流不是闸门）

`/ask` 有每 IP 限流（3/分、20/天），但 `caller_id` 读的是 `X-Forwarded-For` 首段，
代码注释里自己写了「**可伪造，而且这没关系**」——它防的是顺手薅，不是攻击者。

真正的闸门只有一个：**去 DeepSeek 和硅基流动的控制台设消费上限。**

### 应用层还有第二道，但它不能替代第一道

`LLM_DAILY_TOKEN_LIMIT` 按 `llm_usage` 里 **provider 上报的真实 token** 累计当日用量，
超过就在调用之前拒绝，返回 503 并说明「这是成本保护，不是故障」。
prod compose 默认 200 万 token/天，`0` 表示关闭。

它补的是限流管不到的那一半：**限流管一个访客，它管整个部署**——
二十个访客各自都在配额内，账单一样能到；而且限流刻意 fail-open，Redis 一重启就没了。
这一道读数据库，同样 fail-open（守卫不该把成本问题变成故障）。

**但它有三个够不到的地方，所以 provider 侧的上限仍然是第一闸门：**

1. **看不见嵌入与重排**——那是另一个账号，不写进 `llm_usage`；
2. 只能拦经过这段代码的调用；
3. token 不是钱，价格变了它不知道。

设一个数的方法：看 `ahr.cli usage --days 7` 的实际用量，取一个你愿意为「最坏的一天」
付的数字，而不是照抄这里的默认值。

另外注意：Cloudflare 只在流量经过它时才有用。**如果源站 IP 直接可达**，
任何人都能绕过 Cloudflare 直连并自带 `X-Forwarded-For`，限流形同虚设。
可选加固——把源站防火墙限制为只接受 Cloudflare 的 IP 段。

---

## 12. 备份：没演练过的备份不算备份

`backup` 容器每 24 小时 `pg_dump -Fc` 一次，保留 7 天，落在
`infra/compose/backups/`。它先写 `.partial`，用 `pg_restore --list` 验证目录，再原子改名
并生成 `.sha256`；半截或目录损坏的转储不会伪装成好的。

目标机首次部署后立即做一次隔离恢复演练（不会覆盖源库，目标库名被限制为
`ai_hot_radar_restore_verify*`）：

```bash
BACKUP_FILE=/backups/<文件名>.dump docker compose \
  --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml \
  --profile tools run --rm restore-verify
```

两个已知局限，如实记着：
- 本机备份和数据库仍在同一块盘上；生产 preflight 要求明确确认异机/对象存储责任，
  但实际同步必须在拿到目标服务器与存储凭据后配置并复测。
- 保留 7 天意味着**第 8 天才发现的数据损坏无法回滚**。

---

## 13. 部署后的收尾

- [ ] `/eval`、`/ops`、`/ask` 三个页面在公网打得开（这是作品最值得看的部分）
- [ ] `/admin/sources` 能列出信源（说明 VIEWER 凭据配对了）
- [ ] `sitemap.xml` 里是真域名而不是 localhost（靠 `PUBLIC_BASE_URL`）
- [ ] scheduler 日志里能看到 `tick claimed=… ok=…`
- [ ] 隔天回来看 `docker compose logs backup`，确认 `backup ok and catalog verified:`
- [ ] monitor 启动后能收到一次受控失败告警与恢复通知；它只读健康端点与备份目录，
  不挂 Docker socket，也不会自行重启服务。

## 14. 搬家：租期到期前要做的事

租来的机器是有期限的（这次 40 天，且卖家说不能续）。到期时**盘会一起消失**。

**唯一重建不了的是语料。** 1580 条内容是连续采集好几天攒下来的，而且每一条都花过
LLM 加工的钱；代码几分钟就能重新拉起来，语料不能。

`backup` 容器每天都在 `pg_dump`，但**转储就存在这台机器的盘上**——它和数据库一起消失。
所以到期前必须拷走：

```bash
scp root@<旧IP>:~/ai-hot-radar/infra/compose/backups/*.dump ./
```

新机器上恢复：

```bash
scp ./ai_hot_radar-*.dump root@<新IP>:~/ai-hot-radar/infra/compose/backups/
```

```bash
docker compose -f infra/compose/docker-compose.prod.yml exec -T postgres   pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists /backups/<文件名>.dump
```

**域名不用动。** 改 Cloudflare 的 A 记录指向新 IP 就行，几分钟生效——
面试官手里的链接一直有效，这正是当初坚持要域名而不是 IP 的原因。

如果之后要换成**大陆节点 + 备案**：**别等到期才开始**。备案要 1–3 周，
而备案核验不要求域名当时解析到大陆 IP，所以可以**一边让香港这台继续服务、一边备案**，
通过之后再切 DNS，零停机。等过期了才动手，站点会空窗那几周。

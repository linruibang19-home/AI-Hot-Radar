# 换服务器：迁移作业手册

> 面向「旧机到期、新租一台同配置香港机」这一件事。按顺序执行，不要跳步——
> 有两条顺序是硬性的，反了就出事：
> **数据必须在切 DNS 之前恢复完**（第 4 节 → 第 5 节），
> **DNS 必须在起容器之前切**（第 5 节内部，否则 Caddy 签不到证书）。
>
> 现状基线（2026-09-11 实查）：`47.242.229.41`（AS45102 阿里云香港）、
> 10 个容器、数据库 1433 MB、最近一份转储 529 MB、DNS TTL **600 秒**、
> **没有 CDN**（`Via: 1.1 Caddy`，A 记录直指源站）。

---

## 0. 先分清什么会丢、什么不会

这一节决定了后面所有步骤的优先级。

| | 丢了怎么办 | 结论 |
|---|---|---|
| 代码 | `git clone` | 不用迁 |
| 三张业务镜像 | 从 GHCR 拉 | 不用迁 |
| **PostgreSQL 数据** | **重建不了**——5371 条内容是连续采集攒的，每条都花过 LLM 加工的钱 | **必须迁** |
| **`infra/compose/.env`** | **重建不了**——见下 | **必须迁** |
| TLS 证书（`caddy_data`） | Caddy 会重新申请 | 不用迁 |
| `backups/` 3.7 GB | 本机 `D:\Backups\AI Hot Radar` 已有副本 | 不用迁 |

### `.env` 里有一把丢了就没救的钥匙

`LLM_CREDENTIAL_MASTER_KEY`。数据库里存的供应商 API Key 是**用它做信封加密**的
（ADR-0032）。只恢复数据库、不带这把钥匙，那些密文就再也解不开——
**看起来恢复成功，直到第一次调用模型才发现**。

`.env` 共 60 个键，另外这几个同样重建不了：
`POSTGRES_PASSWORD`、`AHR_SUBSCRIPTION_TOKEN_SECRET`（丢了所有已发出的订阅确认链接失效）、
`INTERNAL_SERVICE_TOKEN`、`AHR_ADMIN_*_TOKEN`。

### 采集系统会自己追上

游标存在数据库里。恢复之后，下一轮采集从转储那一刻继续，**这期间各信源发布的内容会被正常抓回来**。
所以「转储 → 切换」之间的间隔不会丢语料，只会丢这段时间的 RAG 提问记录（量很小，可接受）。

**这一点让整件事简单了很多**：不需要停机做一致性快照，不需要双写。

---

## 1. 到期前 ≥3 天：把不可逆的东西弄到手

这几条做完，就算旧机第二天突然消失也不会丢东西。

```bash
# ① .env —— 最重要的一件，先做
scp -i ~/.ssh/ai_hot_radar_deploy_ed25519 \
  deploy@47.242.229.41:/opt/ai-hot-radar/infra/compose/.env \
  "D:/Backups/AI Hot Radar/env-backup-$(date +%Y%m%d).txt"
```

```bash
# ② 立刻触发一份新转储，不要等当天的定时任务
# 常驻的 backup 容器是 sleep 循环，直接 run 会跑完一轮然后挂着睡一天；
# BACKUP_RUN_ONCE 就是为这种手动场景留的。
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@47.242.229.41 \
  'cd /opt/ai-hot-radar && docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml run --rm -e BACKUP_RUN_ONCE=true backup && ls -lht infra/compose/backups | head -5'
```

它会自己写 `.sha256` 旁文件，并且先 `pg_dump` 到 `.partial`、`pg_restore --list` 过了才改名——
所以目录里出现的 `.dump` 一定是完整的。

③ **在服务器上先验，再下载**——先验能省掉一次 529 MB 的无效传输。
仓库里已经有现成的演练服务，不用手搓：

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@47.242.229.41 \
  'cd /opt/ai-hot-radar && BACKUP_FILE=/backups/<刚才那个文件名>.dump docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml --profile tools run --rm restore-verify'
```

它做的事比肉眼看文件大小严格得多：核对 `.sha256` 旁文件 → `pg_restore --list` 探伤 →
恢复进一个隔离库 → 和线上库比 **Flyway 版本**和 `source/content_item/content_chunk/story/report`
五张表的行数 → 删掉隔离库。看到 `restore verify OK` 才算这份转储可用。

```bash
# ④ 确认 OK 之后再拉到本机（注意 .dump* 通配，sha256 旁文件要一起拿）
scp -i ~/.ssh/ai_hot_radar_deploy_ed25519 "deploy@47.242.229.41:/opt/ai-hot-radar/infra/compose/backups/<文件名>.dump*" "D:/Backups/AI Hot Radar/"
```

```bash
# ⑤ check.sh 只存在于旧机的 ~ 下，没进仓库——旧机没了它就没了
scp -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@47.242.229.41:~/check.sh "D:/Backups/AI Hot Radar/"
```

⑥ **把当前信源基线记下来**，迁完之后要拿它对账，否则「少了几个源」根本看不出来：

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@47.242.229.41 \
  "cd /opt/ai-hot-radar && docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml exec -T postgres psql -U ai_hot_radar -d ai_hot_radar -c 'SELECT status, count(*) FROM source GROUP BY status ORDER BY 2 DESC;'"
```

> 基线参考（2026-09-11）：ACTIVE 128 / QUARANTINED 5 / PROBING 2 / RATE_LIMITED 1 / METADATA_ONLY 1。

> `.env` 里全是明文密钥。拷到本机之后不要提交进 git，也不要放进会同步到云盘的目录。

---

## 2. 顺手做一件只有这次能做的事：测 ASN

七个信源（三个 OpenAI 文档站、`openai-news`、`xai-news`、`venturebeat-ai`、`bair-blog`）
在旧机上被拦，原因是 **AS45102 阿里云香港的网段信誉**，不是地理位置，也不是我们的请求量
（`xai-news` 日均只有 4 次请求照样被封）。

同一个厂商换 IP 基本无效，换厂商才有机会。所以这件事的价值在**选厂商的时候**，
不是在迁完之后——如果能在下单前先拿到一台按小时计费的机器试，那是最划算的两分钟。

**在新机上执行**（第 3 节把 SSH 打通之后、迁数据之前，花两分钟）：

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@<新IP> \
  'for u in https://x.ai/news https://openai.com/index/gpt-5-6 https://developers.openai.com/api/docs/changelog; do echo "$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$u")  $u"; done'
```

- **全 200** → 换厂商成功，迁完后 `sync-sources` 即可让七个信源全部恢复
- **仍 403** → 新 ASN 也被拦，不影响迁移，按原样继续（这些源的新闻内容媒体源都有覆盖）

结果记下来，无论哪种都写进交付记录，省得下次再查一遍。

---

## 3. 新机准备（旧机仍在服务，零风险）

```bash
# 装 Docker、开 80/443、建 deploy 用户、授权同一把公钥
ssh root@<新IP> 'useradd -m -s /bin/bash deploy && usermod -aG docker deploy'
```

把本机公钥装上去（用同一把，本机脚本和计划任务就不用改密钥）：

```bash
ssh-copy-id -i ~/.ssh/ai_hot_radar_deploy_ed25519.pub deploy@<新IP>
```

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@<新IP> \
  'sudo mkdir -p /opt/ai-hot-radar && sudo chown deploy:deploy /opt/ai-hot-radar && git clone https://github.com/linruibang19-home/AI-Hot-Radar.git /opt/ai-hot-radar'
```

把 `.env` 放回去（**不要手敲，一个字符错就排查半天**）：

```bash
scp -i ~/.ssh/ai_hot_radar_deploy_ed25519 "D:/Backups/AI Hot Radar/env-backup-<日期>.txt" deploy@<新IP>:/opt/ai-hot-radar/infra/compose/.env
```

### ⚠ 这里有个会让第 5 节卡住的坑

`deploy-production.sh` 有一条自检：

```sh
if [ "$image_tag" != "sha-$head_sha" ]; then
	echo "deploy ERROR: IMAGE_TAG does not match checkout HEAD" >&2
```

新机 `git clone` 拿到的是**最新的 main**，而 `.env` 里的 `IMAGE_TAG` 是你备份那天的
提交。只要这期间 main 有过任何一次合并，两者就对不上，部署直接退出——
**而且是在 DNS 已经切过来之后才暴露**。现在就对齐，别留到那一刻：

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@<新IP> \
  'cd /opt/ai-hot-radar && grep ^IMAGE_TAG infra/compose/.env && echo "HEAD: sha-$(git rev-parse HEAD)"'
```

两行的 sha 不一致就把仓库切到 `.env` 指定的那个提交（**而不是反过来改 `.env`**——
镜像是按提交打的 tag，GHCR 上必须真有这一张）：

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@<新IP> \
  'cd /opt/ai-hot-radar && git checkout $(grep ^IMAGE_TAG infra/compose/.env | sed "s/^IMAGE_TAG=sha-//")'
```

迁完、跑稳之后，再走正常发布流程升到最新 main。**迁移和升级不要挤在同一天**，
否则出问题分不清是搬家搬坏的还是新代码带的。

其余首次部署的坑（GHCR 登录、内存、镜像拉取）见
[`m5-first-deploy-checklist.md`](m5-first-deploy-checklist.md)，不在这里重复。

---

## 4. 先起数据库，恢复数据

**这一步不要 `up -d` 全部容器**——web 和 core-api 会在空库上启动并跑 Flyway，
和 `pg_restore` 撞车。

```bash
cd /opt/ai-hot-radar && docker compose -f infra/compose/docker-compose.prod.yml --env-file infra/compose/.env up -d postgres && sleep 20
```

转储直接放进 `backups/` 目录——它是 bind mount，容器里就是 `/backups`，
省掉再拷一次：

```bash
scp -i ~/.ssh/ai_hot_radar_deploy_ed25519 "D:/Backups/AI Hot Radar/<文件名>.dump*" deploy@<新IP>:/opt/ai-hot-radar/infra/compose/backups/
```

```bash
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml exec -T postgres pg_restore -U ai_hot_radar -d ai_hot_radar --clean --if-exists --no-owner --exit-on-error /backups/<文件名>.dump
```

`--exit-on-error` 是有意加的：**默认行为是报错继续**，最后打印一句错误数就退出 0，
于是一个缺了几张表的库会看起来恢复成功。

核对（数字要和旧机对得上）：

```bash
docker compose -f infra/compose/docker-compose.prod.yml exec -T postgres psql -U ai_hot_radar -d ai_hot_radar -c "SELECT (SELECT count(*) FROM content_item) AS 内容, (SELECT count(*) FROM content_chunk WHERE is_active) AS 分块, (SELECT count(*) FROM source) AS 信源, (SELECT count(*) FROM report) AS 报告;"
```

---

## 5. 切 DNS —— 顺序不能反

**Caddy 只有在 DNS 已经指向本机时才能签到证书**（HTTP-01 挑战要求 Let's Encrypt
访问 `http://aihotradar.online/.well-known/...` 落到这台机器）。所以：

1. **先**把 A 记录改到 `<新IP>`
2. 等 TTL 过期（**600 秒**，旧机这段时间继续服务，无缝）
3. **再**在新机上 `up -d` 全部容器

```bash
# 确认 DNS 已生效再继续
nslookup aihotradar.online 8.8.8.8
```

```bash
cd /opt/ai-hot-radar && sh infra/scripts/deploy-production.sh
```

部署脚本自带 preflight、`--wait` 和公网 smoke。看到 `deploy OK` 才算成功。

确认证书签发成功：

```bash
docker compose -f infra/compose/docker-compose.prod.yml logs caddy --tail 30 | grep -iE "certificate obtained|error"
```

---

## 6. 验证

把第 1 节 ⑤ 存下来的 `check.sh` 放到新机上跑：

```bash
scp -i ~/.ssh/ai_hot_radar_deploy_ed25519 "D:/Backups/AI Hot Radar/check.sh" deploy@<新IP>:~/
```

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@<新IP> 'sh ~/check.sh'
```

八项都要看，尤其：

- **第 2 项监控自检**：退出码 0
- **第 5 项采集**：最近采集时间是刚才，说明调度真的起来了，而不只是容器 healthy
- **第 6 项信源状态**：和第 1 节 ⑥ 记下的分布对得上
- 浏览器打开 `https://aihotradar.online`，证书有效、首页有内容

还要单独确认一次**停滞信源告警**仍然在工作（它是这次迁移之后最容易静默失效的东西，
因为它依赖容器间网络而不是公网）：

```bash
ssh -i ~/.ssh/ai_hot_radar_deploy_ed25519 deploy@<新IP> \
  'cd /opt/ai-hot-radar && docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml exec -T ai-service curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/health/sources'
```

迁移前后应当一致：旧机现在是 **503**（`openai-news` 与 `venturebeat-ai` 停滞）。
如果新机变成 200，先别高兴——**要么是第 2 节的 ASN 换对了信源真恢复了，
要么是这两个源在新机上还没轮到第一次采集**。用第 5 项的采集时间区分。

---

## 7. 收尾（漏了会在几天后咬人）

```powershell
# ① 本机计划任务硬编码了旧 IP，不改的话异地备份会静默停止
Get-ScheduledTask -TaskName "AI Hot Radar - Pull Production Backup" | ForEach-Object { $_.Actions[0].Arguments }
```

把参数里的 `47.242.229.41` 改成新 IP：

```powershell
$t = Get-ScheduledTask -TaskName "AI Hot Radar - Pull Production Backup"; $a = $t.Actions[0]; $a.Arguments = $a.Arguments -replace '47\.242\.229\.41', '<新IP>'; Set-ScheduledTask -TaskName $t.TaskName -Action $a
```

② **把新机指纹写进 `known_hosts`**——这条漏了的话第 ① 条改对了也没用。
上面那个任务的参数里有 `-o BatchMode=yes -o StrictHostKeyChecking=yes`：
遇到没见过的主机它**不会弹确认，直接失败退出**，于是异地备份就这么无声地停了，
等你发现时已经过去好几周。

```powershell
ssh-keyscan -t ed25519 <新IP> | Out-File -Append -Encoding ascii "$env:USERPROFILE\.ssh\known_hosts"
```

手工跑一次任务，确认真能拉下来（**别只看任务状态是"就绪"**）：

```powershell
Start-ScheduledTask -TaskName "AI Hot Radar - Pull Production Backup"; Start-Sleep 60; Get-ChildItem "D:\Backups\AI Hot Radar" | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, Length, LastWriteTime
```

```powershell
# 清掉旧 IP 的指纹
ssh-keygen -R 47.242.229.41
```

③ 更新 `docs/status/current/production-baseline.md` 的版本、IP 与数据快照。

④ 旧机**先别退租**，留 2–3 天。确认新机跑满一个完整周期（日报生成、邮件投递、
每日备份各成功一次）再关。

---

## 8. 出问题怎么退回

DNS 改回 `47.242.229.41`，600 秒生效。**这也是第 7 节第 ④ 条要留旧机的原因**——
旧机不关，回退就是改一条 DNS 记录的事。

但有个前提要清楚：**回退窗口越晚越贵**。新机一旦开始服务，它就在持续采集、
持续写库；这时候退回旧机，新机这段时间采到的内容就留在新机的库里了。

- **切换当天发现问题** → 直接回退，几乎没有损失，重来一遍即可
- **跑了一两天才发现** → 先在新机上 `BACKUP_RUN_ONCE=true` 做一份转储留底，
  再回退；等问题修好、重新切过去时用这份转储，而不是第 1 节那份旧的

换句话说：**回退之前先备份，哪怕你正急着回退。**

---

## 时间预算

| 阶段 | 耗时 | 能否并行 |
|---|---|---|
| 第 1 节 备份 + 校验 | 30–60 分钟 | 旧机正常服务 |
| 第 2 节 ASN 测试 | 2 分钟 | 旧机正常服务 |
| 第 3 节 新机准备 | 30 分钟 | 旧机正常服务 |
| 第 4 节 恢复数据 | 15–25 分钟（529 MB） | 旧机正常服务 |
| **第 5 节 切 DNS** | **10 分钟窗口** | **唯一有影响的一步** |
| 第 6–7 节 验证收尾 | 30 分钟 | 新机已在服务 |

**实际对外不可用时间接近 0**：DNS 生效前旧机在服务，生效后新机在服务。
唯一的风险窗口是新机 `up -d` 到 smoke 通过之间的几分钟，而那时 DNS 已经切过来了——
所以第 4 节的数据恢复一定要在切 DNS **之前**完成。

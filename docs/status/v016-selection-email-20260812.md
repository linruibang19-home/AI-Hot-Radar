# v0.1.6 精选时间与邮件订阅生产验收

日期：2026-08-12（Asia/Shanghai）

运行基线：`v0.1.6@6f03e75aa2273dcb1c28042c8a122ca54572f286`

在线地址：`https://aihotradar.online`

## 1. “精选全部是 12:00”根因与修复

生产库实查表明信源没有中断。当天原精选 12 条全部来自 7 个 arXiv 学科 feed；这些 feed
都把同一批次日期解析为 `04:00 UTC`，即上海时间 12:00。该值只有“当日批次”的语义，
不是每篇论文恰好在 12:00 发布。旧版同时把 7 个学科 feed 当成 7 个独立出版方，因此
单源上限没有阻止 arXiv 占满 12 个精选位。

`select-v3` 做了三项收口：

1. 精选自然日明确按 `Asia/Shanghai` 计算，避免 UTC 日跨界；
2. 7 个 arXiv feed 归入同一 `arxiv` 来源族，每日最多 3 条；精选中的研究内容最多 4 条；
3. arXiv 在首页显示“当日发布”，不伪造分钟；具有真实时间精度的来源继续显示时分。

发布后生产库当天 12 条精选来自 8 个来源族：arXiv 2、Hugging Face Hub 3、AWS 2，
Google Research、Hugging Face Daily Papers、llama.cpp、Mistral、NVIDIA 各 1；研究内容
共 4 条。7 个 arXiv 源均为 ACTIVE，近 24 小时全部有成功记录且连续失败数为 0。
Chrome 生产截图显示首条为 Google Research 01:04，页面不再出现虚假的 12:00。

## 2. 邮件订阅的真实业务流程

邮件订阅发送的是**整期日报、周报或月报**，不是逐条动态轰炸：

1. 用户在报告页提交邮箱、周期与浏览器 IANA 时区；
2. Core API 始终返回通用 202，并发出 24 小时有效的确认链接；同一邮箱十分钟内不重发；
3. 用户点击链接后，PostgreSQL 才建立 ACTIVE 订阅；
4. 调度器每五分钟检查一次，在用户当地时间 08:30 后选择确认时间之后的最新
   PUBLISHED 报告；确认前的历史报告不会补发；
5. 邮件包含报告标题、摘要、分区条目、每条原始来源入口、站内完整版链接和版本化退订链接；
6. `(subscription_id, report_id)` 唯一键防止同一期重复入队，SMTP 失败按 10/60 分钟
   退避，最多三次，失败不会阻塞采集、精选或报告发布。

v0.1.6 将原先会显示 Markdown 标记的正文改成受限、安全的 HTML 渲染，并在订阅弹窗中
明确展示确认、投递和退订三步。生产库实查已有 1 个 ACTIVE 日报订阅、0 个投递记录：
这表示确认链路已完成；由于不补发确认前的历史日报，第一封正式报告会在下一期日报发布后
进入投递队列，这是预期行为。

## 3. 发布与服务器查看方式

`main` 合并**不会自动修改生产服务器**。标准流程是 PR CI 全绿、合并 main、创建 `v*`
标签、Release workflow 构建三张 `sha-<40位提交>` 镜像，然后服务器 `production` 分支
fast-forward、更新 `IMAGE_TAG` 并执行带 preflight/smoke 的部署脚本。

从当前 Windows 开发机只读查看服务器：

```powershell
ssh -i C:\Users\30244\.ssh\ai_hot_radar_deploy_ed25519 deploy@47.242.229.41
cd /opt/ai-hot-radar
git branch --show-current
git rev-parse HEAD
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml ps
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.prod.yml logs --tail=100 web core-api ai-service
```

不要执行 `cat infra/compose/.env`，不要在服务器直接修改业务源码。代码事实源是 GitHub；
服务器只保存权限 600 的生产配置、数据卷、备份和当前镜像选择。

## 4. 验收证据

- PR #8：Spec、AI Service、Core API、Flyway、Web 五项 CI 全绿；
- Release run `31574920245`：同提交全量门禁和 web/core-api/ai-service 三镜像发布成功；
- Python：Ruff、format、精选相关 41/41；
- Java：JDK 21 `SubscriptionMailerTest` 通过；
- Web：相关 Vitest 23/23，Next.js 15 production build 成功；
- 目标机：preflight、10 容器健康等待和 `/health`、首页、内容、报告、RAG、工程页、
  robots、sitemap、公私边界 smoke 全通过；
- 公网 HTML：包含“当日发布”与“邮件订阅”，不包含当天精选的精确 `12:00`；
- ChromeCodex 内核仍因本机路径初始化报错；回退到本机 Chrome 151 无头实拍完成视觉验收。

## 5. 后续优化顺序

1. **邮件生产化**：自有域名发件服务、SPF/DKIM/DMARC、退信/投诉处理、全局/IP 速率限制；
2. **订阅产品化**：订阅管理链接、主题偏好、暂停投递、隐私和数据保留说明；
3. **精选治理**：把来源族和内容配额移入可审计配置，增加“来源集中度/时间精度”运行指标；
4. **RAG**：继续扩展实体、别名、时间窗、跨语言和同名噪声黄金集，并为 embedding、rerank、
   generation 分别设 P95、熔断与供应商故障证据；
5. **工程维护**：升级 GitHub Actions 中已提示弃用的 action 主版本，持续做备份隔离恢复与
   2C4G 容量水位复核。

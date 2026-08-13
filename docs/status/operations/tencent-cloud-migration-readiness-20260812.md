# 腾讯云新机购买与迁移基线（2026-08-12）

对应任务卡：`TASK-M5-011`。本文记录购买页面核对与后续迁移门，不表示实例已经购买、备案已经
提交或生产已经切换。

## 购买配置结论

| 项目 | 页面选择 | 判断 |
|---|---|---|
| 产品 | 腾讯云轻量应用服务器 | 适合当前低并发、单机 Docker Compose 作品集 |
| 地域 | 广州 | 中国大陆用户访问与后续 ICP 备案方向正确 |
| 套餐 | 2 核 4GB、5Mbps | 当前模型外置、文本业务可用；内存是首要容量边界 |
| 系统盘 | 60GB SSD | 当前阶段足够；必须日志轮转、磁盘告警和异机备份 |
| 月流量 | 500GB | 文本/少量截图足够；不从主机分发大文件 |
| 镜像 | Ubuntu Server 24.04 LTS + Docker 29.6.1 | 兼容；Docker 官方支持 Noble 24.04，仍需创建后验版本/Compose/防火墙 |
| 时长 | 1 年 + 页面赠送 3 个月 | 满足大陆轻量实例申请备案所需的 3 个月以上时长 |
| 数量 | 1 | 当前单机架构正确 |
| 搭配对象存储 | 暂不勾选 | 不阻塞购买；上线前必须另有一份真正异机备份，可后配 COS |
| 页面价格 | 188 元 | 仅视为本次页面报价，提交前复核续费价、流量/带宽与活动不可退款条款 |

腾讯云官方 Docker 应用镜像文档说明其示例底层为 Ubuntu Server 24.04 LTS，并要求以购买页实际
镜像为准：<https://cloud.tencent.com/document/product/1207/60423>。Docker 官方把 Ubuntu Noble
24.04 列为支持平台且提供 29.6.1 包：<https://docs.docker.com/engine/install/ubuntu/>。
Ubuntu 24.04 LTS 标准安全维护到 2029 年 5 月：<https://ubuntu.com/about/release-cycle>。

## 为什么容量够、但不能说“永远够”

当前生产有 2040 条内容、8089 个向量分块和 1622 个 Story，模型推理在供应商侧。主机主要消耗
来自 PostgreSQL/pgvector、Java/Python 运行时、解析任务、镜像、日志和备份。2C4G5M/60GB 对当前
低并发文本产品是合理起点，但需要以下门：

- 4GB 主机配置 swap，并给 JVM/Python/PostgreSQL 设置可解释的资源边界；
- Docker 日志轮转，磁盘 75% warning、85% critical；长期超过 70% 先扩盘；
- 监控 OOM、load、DB pool、外部模型 P95、pipeline backlog 与月流量；
- 数据和备份不能只在同一块 60GB 盘；新机稳定后仍保留异机副本和月度恢复演练。

## 备案与网站名称

广州属于中国大陆地域，域名指向该实例公开提供网站前必须完成 ICP 备案。腾讯云轻量应用服务器
要求用于备案的大陆实例购买时长不少于 3 个月：
<https://cloud.tencent.com/document/product/1207/44376>。

技术产品名 **AI Hot Radar**、域名 `aihotradar.online` 和 GitHub 仓库都无需因换服务器改变；
备案提交时的网站名称、主体材料和展示内容要按腾讯云备案页面与属地管局规则填写，这个“备案网站
名称”可能需要合规中文表述，但不要求代码仓库或产品品牌随机器重命名。

备案期间旧香港站继续对外服务。新广州机只能做部署、恢复和通过临时地址/hosts 的验收；正式域名
不提前解析到未备案大陆服务。

## 新机创建后的首轮验收

```text
系统：Ubuntu 24.04 LTS / amd64 / 时区与 NTP 正常
Docker：docker version；docker compose version；hello-world
账户：专用 deploy 用户 + SSH key；验证后关闭 root/口令
网络：安全组与宿主机仅 22/80/443；内部 API/PG/Redis 不暴露
资源：swap、磁盘、inode、Docker data-root、日志轮转
代码：production checkout 对应 release SHA，不在服务器修改源码
配置：新的低额度供应商 key；权限 600；不从旧机明文复制到聊天/Git
数据：旧机一致性 dump + SHA；新机隔离 restore；Flyway V024；关键计数核对
业务：首页、报告、RAG、引用回跳、订阅确认/测试邮件、scheduler、backup、monitor
```

预装镜像只是省去 Docker 安装，不替代上述主机加固。Docker 官方特别提醒容器端口可能绕过 UFW，
因此要同时核对实际 publish 端口、iptables/`DOCKER-USER` 与云安全组。

## 迁移与回切

1. 旧机保持生产，新机部署同一 release SHA；
2. 降低写入窗口，执行带校验和的 PostgreSQL dump；
3. 新机隔离恢复并核对版本/计数，再启动应用；
4. 用临时地址或本机 hosts 完整 smoke，不让搜索引擎收录；
5. 备案完成后把 DNS TTL 先降到 300–600 秒，再切 A 记录；
6. 连续观察 48–72 小时的 HTTP 5xx、RAG P95、调度、邮件、磁盘和备份；
7. 回退条件触发时恢复旧 A 记录；稳定后再停旧机并轮换全部生产密钥。

## 购买前最后核对

- 广州、2C4G5M、60GB、500GB、Ubuntu 24.04 Docker、1 年 + 赠送期、数量 1；
- 实例是 `x86_64/amd64`；活动价格是否首购专享、是否不退款、续费原价；
- 不额外购买与当前需求无关的对象存储/面板；
- 腾讯云账号实名认证主体与拟备案主体一致或符合备案规则；
- 购买后先把实例 IP 和 SSH 主机指纹记录到私有运维记录，不写公开 README。

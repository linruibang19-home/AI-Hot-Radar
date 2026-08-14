# 06｜部署、安全、运维与服务器迁移

## 当前生产拓扑

生产是单机 Docker Compose：Caddy、Web、Core API、AI Service、Scheduler、Pipeline、PostgreSQL、
Redis、Backup、Monitor 共 10 个容器。Caddy 只开放 80/443；SSH 单独受控；数据库、Redis 和内部 API
不发布宿主机端口。模型推理在 DeepSeek/SiliconFlow，主机不承担 GPU 推理。

## 标准发布链

```text
本地 codex/<task> → 测试 → PR → GitHub Actions
→ 合并 main → release tag → 同提交全量门禁
→ GHCR 三张 sha-<40hex> 镜像
→ 服务器 fast-forward + preflight
→ 部署同一 SHA → migration → health/smoke
→ 成功保留新 SHA；失败回上一 IMAGE_TAG
```

服务器不直接修改业务源码、不保存 GitHub 个人令牌、不临时 build。`main` 是代码事实源，生产
`.env`、PostgreSQL 卷、备份和当前 `IMAGE_TAG` 留在目标机。纯文档提交可以合入 main 而不触发
运行镜像升级；判断线上代码必须看 OCI revision/IMAGE_TAG，不假定 main 永远等于生产。

## 密钥与权限

- 每个环境使用独立、低额度供应商 key；`.env` 权限 600，不进 Git、镜像、日志和聊天；
- SSH 先添加专用密钥和非 root deploy 用户，确认可登录后再关闭 root/口令；
- Docker 组等同 root 权限，只给运维账号；
- 管理 API 使用高熵 VIEWER/OPERATOR，写操作二次确认、幂等键和审计；
- 浏览器不持有 OPERATOR；Web 只代理允许的读取与匿名业务接口。

## 网络与应用安全

- Caddy 自动 TLS 和安全头，内部网络只允许必要服务通信；
- 云安全组与主机规则只开放 22/80/443，Docker 端口还需检查 `DOCKER-USER` 链；
- 采集做 SSRF、重定向重检、大小/超时/限速；
- HTML/Markdown 清洗，Prompt 中把网页标记为不可信数据；
- RAG 工具只读，模型不能调用管理动作；
- 日志脱敏 Authorization、Cookie、API key、邮箱和个人内容。

## 备份、恢复与告警

每日 `pg_dump -Fc` 生成清单和 SHA-256，复制到异机；备份“存在”不等于可恢复，需在隔离数据库
定期 restore、运行 Flyway 并核对关键表计数。当前 RPO ≤ 24h、RTO ≤ 4h；每月恢复演练。

Monitor 检查服务健康、公开 smoke 和备份年龄，并发送故障/恢复通知。重要告警包括 P0 来源连续失败、
全局入站停滞、RAG 空检索率、引用解析失败、API 5xx、磁盘 75%/85%。Redis 不作为备份对象。

## 为什么当前 2C4G 足够

本机主要运行 HTTP、数据库、JVM/Python、文本处理和容器；模型算力在供应商。当前低并发和八千级
分块下，风险先是 4GB 内存、磁盘、镜像/日志/备份增长及外部 API P95，而非 CPU 推理。需要限制
并发、设置容器内存、swap、日志轮转与磁盘告警。60GB 是起点；长期超过 70% 先扩盘，持续 OOM、
DB pool/请求排队或并发增长再升 4C8G。5Mbps/500GB 对文本足够，大图和附件不从该机直出。

### 当前 JVM 与容器预算（2026-08-14 实测）

当前生产宿主机是香港 Ubuntu 22.04.5，系统可见约 3.4 GiB 内存和 2 GiB swap；腾讯云广州
Ubuntu 24.04 仍是备案完成后的迁移目标。Core API 容器上限 512 MiB，实际进程为 Java 21：

```text
java -XX:MaxRAMPercentage=75 -jar app.jar
Max. Heap Size (Estimated): 371.25M
```

不能把 512 MiB 容器上限直接说成 512 MiB heap。剩余空间用于 metaspace、线程栈、code cache、
direct/native memory。读取时 Core API 约 278 MiB；这只是瞬时观察，不是 SLO。生产 10 个容器
均有 memory limit，Redis 另设 128 MiB `maxmemory` + `allkeys-lru`，有界日志防止磁盘失控。

## 迁移到广州 Ubuntu 24.04 的步骤

网站名 **AI Hot Radar** 与域名 `aihotradar.online` 不依赖机器，可以保持不变。迁移不是在新机
`git pull` 后直接替换 DNS，而是平行恢复和可回切发布：

1. 购买广州 2C4G5M、60GB、Ubuntu 24.04 Docker 镜像；保留旧香港站；
2. 更新系统，校验 Docker/Compose，建立 deploy 用户、SSH key、swap、日志轮转和安全组；
3. 在新机部署与 GitHub release 对应的同一 SHA 镜像，先不绑定正式域名；
4. 旧机停止写入窗口或做一致性 `pg_dump`，校验后在新机隔离恢复；
5. 用 hosts/临时子域 smoke 首页、报告、RAG、邮件、调度、备份和告警；
6. 中国大陆服务完成 ICP 备案后，降低 DNS TTL，把 A 记录切到新 IP；
7. 观察 48–72 小时，旧机保留回退；稳定后再停旧机并轮换所有生产密钥。

Ubuntu 24.04 LTS 与项目 Docker Compose 没有应用层冲突；宿主机只需要标准 Docker Engine、Compose v2、
Git/SSH/curl 和正确时钟。预装 Docker 镜像仍要核对来源、版本、daemon 配置、防火墙和自动更新，
不能因为“预装”跳过加固。

## 扩容顺序

先用观测确定瓶颈：连接池/SQL/索引、外部模型长尾、Worker backlog、内存或网络。常见顺序是
扩盘/内存 → 调整并发与连接池 → 增加 Worker → 只读/索引优化 → 经 ADR 引入队列或独立搜索。
不从单机直接跳 Kubernetes。

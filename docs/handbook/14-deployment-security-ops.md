# 14｜部署、安全、发布、备份与运维

## 1. 生产交付模型

代码合入 `main` 后，GitHub Actions 构建并发布按 commit SHA 标识的 web/core-api/ai-service 镜像
到 GHCR。生产不会因为 main 更新自动漂移；部署时服务器拉指定 `IMAGE_TAG`，Compose 重建，
smoke 成功后再把新版本视为生产。旧镜像 tag 保留用于回滚。

## 2. 网络边界

- 公网只开放 80/443 到 Caddy；
- SSH 只允许密钥和受控地址；
- Core API、AI Service、PostgreSQL、Redis 无公网端口；
- Caddy 自动签发/续期 TLS；
- 管理 token、数据库口令、provider key 只在服务器 `.env`；
- `.env` 不进 git、不粘进公开日志。

## 3. CI/CD 门禁

典型流水线包含：规格/配置校验、Python lint/test、Java test、Web typecheck/lint/test/build、Flyway
迁移、镜像构建与安全/敏感串检查。生产部署还需 Compose preflight：变量必填、域名、镜像 tag、
预算确认、备份目标和内部端口。

## 4. 数据迁移

Flyway 容器先执行迁移，成功后应用才进入 ready。迁移必须前向兼容滚动窗口：先加字段/表，再发
读写代码，最后才删除旧路径。生产数据库不能手工 CREATE/ALTER 来“临时修一下”。

## 5. 备份与恢复

备份至少包含 PostgreSQL 逻辑/物理恢复材料和必要配置的加密异机副本。验收步骤：检查文件存在
只是第一层；还要在隔离目录恢复、启动兼容版本、跑 schema 和业务 smoke。Redis 数据不是业务
恢复源，清空后系统应能重新建立缓存。

## 6. 可观测性

关键维度：source freshness/fulltext success、processing backlog、provider calls/tokens/latency、RAG
阶段耗时、报告生成/发布、subscription delivery、HTTP error、容器健康、磁盘与备份年龄。日志
带 trace id、服务、操作和稳定错误码，但不带密钥、完整受限正文或用户邮箱。

## 7. 2C4G 容量治理

- PostgreSQL/Redis/Java/Python/Next 均设内存边界；
- scheduler/pipeline 批量和并发有上限；
- 模型计算走外部 API，不在本机跑大模型；
- Docker local 日志轮转；
- BuildKit/旧镜像定期清理，永不自动 prune volumes；
- 连接池总和按数据库 `max_connections` 反推。

## 8. 发布与回滚

```text
CI 通过
→ 记录当前 tag/数据库备份
→ 拉取 SHA 镜像
→ Flyway migrate
→ Compose up
→ health + 页面 + RAG + 邮件 dry-run smoke
→ 观察错误/资源
```

应用回滚使用旧 SHA 镜像；数据库回滚优先使用向前修复，只有破坏性事故才恢复备份。发布不能把
“git pull 成功”当作“生产成功”。

## 9. 迁移到新服务器

在备案期间可平行准备 Ubuntu 24.04 Docker 主机：加固 SSH、安装 Compose、同步部署目录和秘密、
恢复数据库副本、用 hosts/临时域名验收。最终停写/短窗口备份恢复，切 DNS A 记录，原网站名称
和域名可保持不变。保留旧机回切窗口，确认新机邮件出站、证书和备份后再下线。

## 10. 代码与文档

- `infra/compose/`
- `infra/caddy/`
- `infra/scripts/`
- `.github/workflows/`
- `docs/design/m5-deployment.md`
- `docs/spec/11-end-to-end-runbook.md`


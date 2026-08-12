# 作品集 README 与面试材料补全验收（2026-08-12）

任务卡：`TASK-M5-011`。本卡只修改公开文档与迁移基线，不改变运行代码、RAG 策略、数据库、API、
生产镜像或生产数据。

## 完成范围

- 根 README 重构为 30 秒项目定位、3 分钟产品/架构、30 分钟数据/RAG/生产深挖；
- 业务架构、系统拓扑、核心技术栈、服务边界、数据链、RAG 全链路、指标、负实验、报告/邮件、
  部署安全、运行方式、已知边界与文档导航均进入首个项目入口；
- `docs/interview/` 从五份混合稿拆成 00–10 十一份独立材料，并删除旧稿避免双份漂移；
- 腾讯云广州 2C4G5M/60GB/Ubuntu 24.04 Docker 购买与迁移条件记录在
  `tencent-cloud-migration-readiness-20260812.md`；
- 生产数据只读复核为 140/104 信源、2040 内容、8089/8089 分块、1622 Story、218 问答、
  915 引用；运行仍为 `v0.1.7@c1c6918`，10 个容器运行且核心服务 healthy。

## 文档结构

```text
docs/interview/
├── 00-project-one-pager.md
├── 01-business-and-architecture.md
├── 02-ingestion-and-data-model.md
├── 03-rag-deep-dive.md
├── 04-backend-and-consistency.md
├── 05-frontend-product.md
├── 06-deployment-security-ops.md
├── 07-interview-question-bank.md
├── 08-resume-and-star-stories.md
├── 09-system-design-whiteboard.md
├── 10-demo-script.md
└── README.md
```

## 验收证据

```text
python scripts/validate_spec.py
PASS: sources=140, profiles=9, social_ids=38

git diff --check
PASS

本地 Markdown 检查
PASS: 15 份入口/面试/状态文档的相对链接与图片存在
PASS: 00–10 共 11 份编号文档
PASS: fenced code blocks 成对
PASS: 变更文件无 API key、GitHub token 或私钥模式
```

GitHub PR/CI 证据在合入前补写。纯文档变更不触发生产镜像发布，避免让运行代码与文档提交混淆。

## 剩余风险与下一任务

- 文档是代码与生产快照的解释，不替代持续运行证据；面试前重新读 `/ops` 和当前 handoff；
- 腾讯云实例尚未购买，Ubuntu 24.04 兼容判断需要在真实主机上复验 Docker/Compose/防火墙；
- 下一张任务卡是新机平行部署与恢复验收；备案和 DNS 切换必须在主人完成购买、实名与备案流程后执行。

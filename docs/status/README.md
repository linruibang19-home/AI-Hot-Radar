# 状态、验收与历史证据索引

`status/` 保存实际运行产生的事实。这里既有当前入口，也有历史快照和逐题评测；历史文件不能
用来推断当前生产状态，但不能删除，因为它们记录问题、假设、负结果和验收证据。

## 当前入口

| 用途 | 文档 |
|---|---|
| 当前生产、提交、数据和下一步 | [handoff-20260812.md](handoff-20260812.md) |
| 完整项目历史与问题根因 | [project-status.md](project-status.md) |
| 完整交付导航 | [../spec/12-delivery-index.md](../spec/12-delivery-index.md) |
| 腾讯云迁移 | [tencent-cloud-migration-readiness-20260812.md](tencent-cloud-migration-readiness-20260812.md) |
| 仓库清理与归档 | [repository-hygiene-20260812.md](repository-hygiene-20260812.md) |
| 实现事实与文档教材审计 | [documentation-audit-20260813.md](documentation-audit-20260813.md) |

## RAG 证据

| 范围 | 文档 |
|---|---|
| 当前发布门与人工审计 | [rag-specialist-audit-20260811.md](rag-specialist-audit-20260811.md) |
| 安全、超时、缓存与 SLO | [rag-security-performance-20260811.md](rag-security-performance-20260811.md) |
| 产品成熟度与对标 | [rag-product-readiness-20260810.md](rag-product-readiness-20260810.md) |
| RAG UI | [rag-ui-polish-20260811.md](rag-ui-polish-20260811.md) |
| 质量/运行工程页 | [rag-operations-ui-20260811.md](rag-operations-ui-20260811.md) |
| B1–B15、生成、专项与延迟原始产物 | [eval/README.md](eval/README.md) |

`eval/*.json` 是版本化实验结果，不是缓存。它们只有在模型、语料截止时间、配置和样本量一起
给出时才有意义；站内 `/eval` 是由其中选定轮次生成的发布摘要，不是实时监控。

## 产品与上线闭环

| 范围 | 文档 |
|---|---|
| 报告阅读 | [report-reader-20260811.md](report-reader-20260811.md) |
| 报告发布状态机 | [report-publication-20260811.md](report-publication-20260811.md) |
| 邮箱订阅 | [report-subscriptions-20260811.md](report-subscriptions-20260811.md) |
| 精选时间与真实订阅验收 | [v016-selection-email-20260812.md](v016-selection-email-20260812.md) |
| 模型配置 | [generation-model-selection-20260811.md](generation-model-selection-20260811.md) |
| 生产预检 | [production-preflight-20260811.md](production-preflight-20260811.md) |
| 首次生产部署 | [production-deployment-20260811.md](production-deployment-20260811.md) |
| Docker 存储控制 | [docker-storage-controls-20260812.md](docker-storage-controls-20260812.md) |

## 作品集与体验

- [navigation-performance-20260812.md](navigation-performance-20260812.md)：页面点击反馈与导航回归；
- [portfolio-closeout-20260812.md](portfolio-closeout-20260812.md)：工程页面语义和截图封版；
- [portfolio-interview-completion-20260812.md](portfolio-interview-completion-20260812.md)：README 与面试材料验收。

## 历史快照

- `handoff-20260810.md`：M4 末期历史状态，已被 08-11 与 08-12 交接取代；
- `handoff-20260811.md`：首次上线前后过渡状态，已被 08-12 交接取代；
- `prelaunch-release-gate-20260811.md`：上线前门禁，不代表当前运行版本；
- `m1-canary-evidence.*`：M1 信源阶段证据。

历史快照保留原路径以维持引用和审计链。需要“现在是什么状态”时只读当前入口；需要“为什么
变成这样”时再沿历史与 eval 记录回溯。

# 状态与证据索引

`status/` 保存实际运行产生的事实，只有两层：

- [`current/`](current/)：**现在是什么**。只放最新交接和生产基线，随生产变更更新；
- [`evidence/`](evidence/)：**当时发生了什么**。带日期的验收、实验、压测、发布与事故记录，冻结后
  不改数字。它们不能用来推断当前生产状态，但记录了问题、假设、负结果和验收证据，不能删除。

被取代的交接和累计开发日志在 [`../archive/`](../archive/)；逐题评测 JSON 在
[`../../data/eval-runs/`](../../data/eval-runs/README.md)。事实优先级与写入规则见
[`../README.md`](../README.md)。

## 当前

| 文档 | 内容 |
|---|---|
| [handoff-20260922.md](current/handoff-20260922.md) | **冷启动先读**：线上登录、版本、数据、备份、本地环境与下一步 |
| [production-baseline.md](current/production-baseline.md) | 生产版本、服务、数据、质量与已知边界的基线快照 |

## 证据

### 综合核查

| 文档 | 内容 |
|---|---|
| [project-audit-20260922.md](evidence/project-audit-20260922.md) | **完成度与质量全面核查**：信源、RAG 离线/线上对照与 6 个新发现问题 |

### RAG 与评测

| 文档 | 内容 |
|---|---|
| [rag-tuning-log.md](evidence/rag-tuning-log.md) | **B1–B15、生成侧与延迟的调优纪要**，含负结果；JSON 对照见 `data/eval-runs/` |
| [rag-product-readiness-20260810.md](evidence/rag-product-readiness-20260810.md) | RAG 全链路、成熟产品对标与优化顺序 |
| [planner-diff-20260810.md](evidence/planner-diff-20260810.md) | Planner 对照：正则 0.6667 vs LLM 0.9067 |
| [query-type-sweep-20260810.md](evidence/query-type-sweep-20260810.md) | query_type 标签几乎不改变检索结果 |
| [rag-specialist-audit-20260811.md](evidence/rag-specialist-audit-20260811.md) | 专项发布门禁与人工引用审计 |
| [rag-security-performance-20260811.md](evidence/rag-security-performance-20260811.md) | 安全、超时、缓存与 SLO |
| [rag-ui-polish-20260811.md](evidence/rag-ui-polish-20260811.md) | 问答界面精修 |
| [rag-operations-ui-20260811.md](evidence/rag-operations-ui-20260811.md) | 质量与运行页面 |
| [generation-model-selection-20260811.md](evidence/generation-model-selection-20260811.md) | DeepSeek 生成模型切换 |
| [rag-corpus-audit-20260813.md](evidence/rag-corpus-audit-20260813.md) | 语料、原文切块与向量覆盖审计 |
| [golden-refresh-20260830.md](evidence/golden-refresh-20260830.md) | 黄金集刷新（标注阶段） |
| [listing-articles-undated-20260830.md](evidence/listing-articles-undated-20260830.md) | HTML 列表档位抽不到发布日期 |

`/eval` 页面是 `scripts/build_eval_summary.py` 从选定 JSON 生成的发布快照，不是实时监控。

### 信源、内容与主题

| 文档 | 内容 |
|---|---|
| [m1-canary-evidence.md](evidence/m1-canary-evidence.md) | M1 信源探测验收（逐源原始数据在同名 `.json`） |
| [story-public-experience-20260813.md](evidence/story-public-experience-20260813.md) | Story 公开入口有效性 |
| [topic-map-quality-20260813.md](evidence/topic-map-quality-20260813.md) | 主题地图关联分层与语料克隆验收 |
| [topic-map-golden-set-20260813.md](evidence/topic-map-golden-set-20260813.md) | 主题地图关系黄金集第一阶段 |
| [topic-timeline-performance-20260813.md](evidence/topic-timeline-performance-20260813.md) | 主题/厂商时间线与导航性能 |
| [domestic-source-expansion-20260817.md](evidence/domestic-source-expansion-20260817.md) | 中文信源 Sitemap 回源与全文门禁 |

### 报告与订阅

| 文档 | 内容 |
|---|---|
| [report-reader-20260811.md](evidence/report-reader-20260811.md) | 报告阅读体验与结构化只读模型 |
| [report-publication-20260811.md](evidence/report-publication-20260811.md) | 非阻塞报告发布状态机 |
| [report-subscriptions-20260811.md](evidence/report-subscriptions-20260811.md) | 邮箱订阅与定时投递 |
| [v016-selection-email-20260812.md](evidence/v016-selection-email-20260812.md) | 精选时间与真实订阅生产验收 |

### 发布与部署

| 文档 | 内容 |
|---|---|
| [prelaunch-release-gate-20260811.md](evidence/prelaunch-release-gate-20260811.md) | 上线前最终本地门禁 |
| [production-preflight-20260811.md](evidence/production-preflight-20260811.md) | 生产部署预检与恢复门禁 |
| [production-deployment-20260811.md](evidence/production-deployment-20260811.md) | 首次生产部署 |
| [production-deployment-v015-20260815.md](evidence/production-deployment-v015-20260815.md) | v0.1.15 中文公共阅读门与教材发布 |
| [ci-actions-node24-20260817.md](evidence/ci-actions-node24-20260817.md) | GitHub Actions Node 24 运行时升级 |
| [model-console-release-20260819.md](evidence/model-console-release-20260819.md) | v0.1.19 发布 |
| [ui-type-scale-release-20260819.md](evidence/ui-type-scale-release-20260819.md) | v0.1.20 发布 |
| [changelog-recovery-release-20260831.md](evidence/changelog-recovery-release-20260831.md) | v0.1.21 发布 |

### 运维、性能与事故

| 文档 | 内容 |
|---|---|
| [navigation-performance-20260812.md](evidence/navigation-performance-20260812.md) | 页面点击反馈与导航回归 |
| [docker-storage-controls-20260812.md](evidence/docker-storage-controls-20260812.md) | Docker 磁盘增长控制 |
| [tencent-cloud-migration-readiness-20260812.md](evidence/tencent-cloud-migration-readiness-20260812.md) | 腾讯云新机与迁移基线 |
| [loadtest-local-baseline-20260813.md](evidence/loadtest-local-baseline-20260813.md) | 本地 Web/Core/AI、PostgreSQL、Redis 分层压测 |
| [loadtest-m5-020-production-20260814.md](evidence/loadtest-m5-020-production-20260814.md) | 香港 2C4G 低风险生产压测（不是容量寻顶） |
| [architecture-review-20260818.md](evidence/architecture-review-20260818.md) | 代码、仓库、生产机三方通读核查 |
| [incident-server-loss-20260918.md](evidence/incident-server-loss-20260918.md) | 事故复盘：生产服务器到期消失，从转储重建 |

压测证据必须写明日期、Git SHA、硬件/容器限制、数据规模、脚本、请求组合、持续时间、缓存冷热、
错误率和 P50/P95/P99；脚本入口见 [`infra/loadtest/`](../../infra/loadtest/README.md)。

### 文档与作品集

| 文档 | 内容 |
|---|---|
| [repository-hygiene-20260812.md](evidence/repository-hygiene-20260812.md) | 全仓盘点、清理与可恢复归档 |
| [portfolio-closeout-20260812.md](evidence/portfolio-closeout-20260812.md) | 工程页面语义和截图封版 |
| [portfolio-interview-completion-20260812.md](evidence/portfolio-interview-completion-20260812.md) | README 与面试材料验收 |
| [documentation-audit-20260813.md](evidence/documentation-audit-20260813.md) | 实现事实校准与文档教材重构 |
| [documentation-refresh-20260817.md](evidence/documentation-refresh-20260817.md) | 文档事实源与全仓一致性复核 |

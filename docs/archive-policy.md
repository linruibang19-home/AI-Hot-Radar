# 文档分级、冻结与归档规则

## 1. 目的

文档漂移通常不是因为缺少文件，而是同一个事实同时存在于规格、状态、README 和面试稿，更新时
只改了一处。本规则规定每类文档能回答什么、能否覆盖历史、怎样声明当前或冻结。

## 2. 五种状态

| 标签 | 位置 | 含义 | 更新规则 |
|---|---|---|---|
| CURRENT | README、handbook、handoff、runbook | 当前实现/入口 | 随代码和生产变更更新 |
| SPEC/ADR | `docs/spec`、`docs/adr` | 需求、锁定边界、决策 | 物质变化先 ADR；旧 ADR 不改写历史 |
| LIVING DESIGN | `docs/design/current` | 当前实现方案 | 记录变更原因与版本 |
| EVIDENCE FROZEN | `docs/status`、`status/eval` | 日期环境下的不可再生证据 | 不改数字；新增更晚快照 |
| LEGACY FROZEN | `docs/archive`、`docs/status/history` | 已取代讲稿/交接 | 顶部标冻结及替代入口 |

## 3. 单一入口

- 当前生产：`docs/status/current/production-baseline.md`；日期化交接只保存发布当时的完整证据；
- 当前任务：`docs/spec/08-roadmap-ai-ide.md` 中最后一个状态为执行中的任务卡；
- 当前架构与数据：相关 spec + 最新 ADR；
- 完整学习：`docs/handbook/README.md`；
- 面试训练：`docs/interview/README.md`；
- 历史证据：`docs/status/README.md` 分类索引。

## 4. 动态数字

内容、chunk、Story、ACTIVE source、测试数、容器数和延迟只能以下列形式出现：

- 带日期/环境的快照；或
- 从 CI/数据库动态生成的当前值；或
- 明确写“示例/目标/历史”。

根 README 可以保留最近一次快照，但必须链接 handoff 并声明不是固定承诺。历史 status 不为了
追上当前而改写原数字。

仓库 `main`、Release 标签和生产 `IMAGE_TAG` 必须分开写。仅含文档的主分支提交不等于生产
业务镜像已重新发布。

## 5. 归档方式

默认先逻辑冻结；当自动链接校验能够覆盖仓库内引用、并确认 Git rename 保留历史后，可以在独立
文档治理任务中物理归档。开发方案与旧讲稿进入 `docs/archive/`，过时交接进入
`docs/status/history/`；评测 JSON、失败实验、迁移、fixture 和生产验收永不当缓存清理。

## 6. 自动门禁

`scripts/validate_docs.py` 检查相对 Markdown 链接、handbook/interview 必需章节、当前核心规格中
已经纠正的旧架构说法，以及 README 当前测试口径。CI 与 `validate_spec.py` 一起执行。

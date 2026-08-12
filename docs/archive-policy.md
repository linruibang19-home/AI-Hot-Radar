# 文档分级、冻结与归档规则

## 1. 目的

文档漂移通常不是因为缺少文件，而是同一个事实同时存在于规格、状态、README 和面试稿，更新时
只改了一处。本规则规定每类文档能回答什么、能否覆盖历史、怎样声明当前或冻结。

## 2. 五种状态

| 标签 | 位置 | 含义 | 更新规则 |
|---|---|---|---|
| CURRENT | README、handbook、handoff、runbook | 当前实现/入口 | 随代码和生产变更更新 |
| SPEC/ADR | `docs/spec`、`docs/adr` | 需求、锁定边界、决策 | 物质变化先 ADR；旧 ADR 不改写历史 |
| LIVING DESIGN | `docs/design` | 当前实现方案和评测设计 | 记录变更原因与版本 |
| EVIDENCE FROZEN | `docs/status`、`status/eval` | 日期环境下的不可再生证据 | 不改数字；新增更晚快照 |
| LEGACY FROZEN | 被新入口取代的讲稿/交接 | 保留链接和历史语境 | 顶部标冻结及替代入口 |

## 3. 单一入口

- 当前生产：`docs/status/handoff-20260812.md`（后续用新日期文件取代并更新索引）；
- 当前任务：`docs/spec/08-roadmap-ai-ide.md`；
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

## 5. 归档方式

默认采用**逻辑归档而非移动文件**：在顶部加冻结说明，并在 `docs/status/README.md` 注册替代入口。
这样不会破坏外链、PR 证据和历史引用。只有确认没有引用且内容是纯重复副本时，才在单独任务中
移动/删除；评测 JSON、失败实验、迁移、fixture 和生产验收永不当缓存清理。

## 6. 自动门禁

`scripts/validate_docs.py` 检查相对 Markdown 链接、handbook/interview 必需章节、当前核心规格中
已经纠正的旧架构说法，以及 README 当前测试口径。CI 与 `validate_spec.py` 一起执行。


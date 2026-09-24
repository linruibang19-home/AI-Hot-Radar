# 文档导航

`docs/` 只放给人读的文字，也是全部文档规则的唯一出处。评测原始 JSON 在
[`../data/eval-runs/`](../data/eval-runs/README.md)，跨服务契约（OpenAPI、JSON Schema）在
[`../contracts/`](../contracts/)。

## 从哪里开始

| 想知道什么 | 读哪里 |
|---|---|
| 现在线上什么状态、下一步做什么 | [`status/current/`](status/current/) 里日期最新的 `handoff-*.md`，当前是 [handoff-20260922](status/current/handoff-20260922.md) |
| 生产版本、服务与数据基线 | [`status/current/production-baseline.md`](status/current/production-baseline.md) |
| 系统怎么工作、代码在哪 | [`handbook/`](handbook/README.md)、[`code-map.md`](code-map.md) |
| 为什么这样选、何时回滚 | [`adr/`](adr/README.md) |
| 产品与架构必须是什么 | [`spec/00-master-spec.md`](spec/00-master-spec.md)，其余规格见文末清单 |
| 当前任务 | [`spec/08-roadmap-ai-ide.md`](spec/08-roadmap-ai-ide.md) 中最后一张状态为执行中的任务卡 |
| 面试准备 | [`interview/`](interview/README.md) |
| 某次验收、实验、压测或事故当时发生了什么 | [`status/README.md`](status/README.md) |

## 目录与更新规则

| 目录 | 内容 | 更新规则 |
|---|---|---|
| `spec/` | 锁定的产品、架构、数据、接口规格 | 冲突时以 `00-master-spec.md` 为准；实质变更先写 ADR |
| `adr/` | 偏离或补充规格的决策 | 只追加，不改写历史 ADR |
| `design/` | 规格没规定、实现必须定下来的方案，以及运维作业手册 | 活文档，随实测修订 |
| `handbook/` | 完整工程教材：01–15 主线，16–23 按问题选读的专题 | 随代码更新；动态数字链接 `status/current/` |
| `interview/` | 把事实训练成答辩表达 | 引用数字须标日期和环境 |
| `status/current/` | 现在是什么：最新交接与生产基线 | 随生产变更更新，必须写「截至」日期 |
| `status/evidence/` | 带日期的验收、实验、压测、发布与事故证据 | 冻结：不改数字，只新增更晚的快照 |
| `archive/` | 被取代的方案、交接、讲稿与累计开发日志 | 冻结：顶部写明替代入口，不再追赶当前代码 |
| `assets/screenshots/` | 根 README 的截图 | `node scripts/refresh-screenshots.mjs docs/assets/screenshots` |

判断写到哪里：「规格没说，需要定一个做法」→ `design/`；「规格说了 A，我们要做 B」→ **先写
ADR**，再改 `design/`；「跑出来的数字」→ `status/`。

`design/` 的两条硬约定：

1. **每份文档必须有「变更记录」小节**，写明方案因何被修正。多数调整源于实测发现的缺陷，
   不留原因，下一个人会把同一个坑再踩一遍。
2. **参数必须标注来源**：`实测标定` / `规格规定` / `待评测标定`，禁止来历不明的魔数。

## 事实优先级

```text
当前环境实时查询
  > status/current/ 中带日期的交接与生产基线
  > status/evidence/ 中的日期化验收证据
  > spec / ADR 中的目标与锁定决策
  > handbook / interview 中的讲解示例
```

## 动态数字

内容、chunk、Story、信源、测试数、容器数和延迟只能以三种形式出现：带日期和环境的快照；
从 CI 或数据库动态生成的当前值；明确写「示例 / 目标 / 历史」。历史证据不为追上当前而改写原数字。

仓库 `main`、Release 标签和生产 `IMAGE_TAG` 必须分开写：仅含文档的提交不等于生产镜像已重新发布。

## 归档与门禁

- 文档不再代表当前事实时，用 `git mv` 移进 `archive/`（保留 Git 历史），并在顶部写替代入口。
- 评测 JSON、失败实验、迁移、fixture 和生产验收是不可再生证据，永不当缓存删除。
- `scripts/validate_docs.py` 检查全部相对 Markdown 链接、handbook/interview 必需章节和已纠正的
  旧说法；CI 与 `scripts/validate_spec.py` 一起执行。

## 规格清单

| 文件 | 作用 |
|---|---|
| [00-master-spec.md](spec/00-master-spec.md) | 总规格与 ADR-001~011 锁定决策 |
| [01-product-requirements.md](spec/01-product-requirements.md) | 页面、角色与产品验收 |
| [02-system-architecture.md](spec/02-system-architecture.md) | 服务边界、状态机、部署 |
| [03-data-ingestion.md](spec/03-data-ingestion.md) | 数据模型、去重、切块、Story |
| [04-rag-agent-design.md](spec/04-rag-agent-design.md) | 时间与事件感知 RAG |
| [05-api-contract.md](spec/05-api-contract.md) | HTTP 与任务契约 |
| [06-frontend-spec.md](spec/06-frontend-spec.md) | 路由、页面、组件状态 |
| [07-quality-security-ops.md](spec/07-quality-security-ops.md) | 测试、安全、版权、运维 |
| [08-roadmap-ai-ide.md](spec/08-roadmap-ai-ide.md) | M0–M5 里程碑与任务卡 |
| [09-source-registry-fulltext.md](spec/09-source-registry-fulltext.md) | 信源分层与全文标准 |
| [10-source-adapter-implementation.md](spec/10-source-adapter-implementation.md) | 各类接口读取与字段映射 |
| [11-end-to-end-runbook.md](spec/11-end-to-end-runbook.md) | 联调与恢复流程 |
| [12-delivery-index.md](spec/12-delivery-index.md) | 交付物与证据索引 |

# ADR-0012：`discovery_url` 改为按 profile 条件必填

日期：2026-08-01
状态：已接受
关联：`AHR-SOURCE-900`、`schemas/source-registry.schema.json`、`config/ingestion-profiles.yaml`

## 背景

执行 `TASK-M0-001` 时运行 `scripts/validate_spec.py`，140 个信源中有 **64 个校验失败**，错误均为 `'discovery_url' is a required property`：

| profile | 数量 | 实际使用的字段 |
|---|---:|---|
| `github_release_api` | 53 | `repository`（如 `openai/openai-python`） |
| `arxiv_feed_paper` | 7 | `subject`（如 `cs.AI`） |
| `github_repo_activity` | 4 | `repository` |

该问题在基线提交 `819d040` 中已存在，**不是仓库重构引入的**。

## 问题定位

`config/ingestion-profiles.yaml` 对这三类 profile 使用**模板拼接**端点，而非字面 URL：

```text
github_release_api   → https://api.github.com/repos/{repository}/releases?per_page=100&page={page}
github_repo_activity → https://api.github.com/repos/{repository}
arxiv_feed_paper     → https://rss.arxiv.org/rss/{subject}
```

因此这 64 条来源**不应该**有 `discovery_url`——URL 在运行时由 `repository`/`subject` 推导。数据是对的，schema 是错的。

Schema 原本已经用 `allOf` 表达了正确意图（`github_release_api` 要求 `repository`），但同时把 `discovery_url` 放进顶层 `required`，使这些条目永远无法通过校验。两条规则自相矛盾。

## 决策

1. 从顶层 `required` 移除 `discovery_url`；
2. 新增条件规则：profile **不属于**上述三类时，`discovery_url` 必填；
3. 补充 `github_repo_activity` 要求 `repository`、`arxiv_feed_paper` 要求 `subject`；
4. 新增 `subject` 属性定义（此前 schema 未声明）。

## 备选方案

- **给 64 条来源补 `discovery_url`**：否决。会把运行时推导的 URL 冻结成静态值，GitHub API 分页与 `{page}` 模板冲突，且与 `ingestion-profiles.yaml` 重复维护。
- **放宽为 `additionalProperties` 全通过**：否决。会让真正缺 URL 的普通 RSS 来源静默通过，失去门禁意义。

## 后果

- 校验通过：`sources=140 profiles=9 social_ids=38`；
- 已用 7 个用例验证 schema 仍能拒绝非法输入（缺 `discovery_url` 的 RSS、缺 `repository` 的 GitHub、缺 `subject` 的 arXiv、`restricted` 却 `enabled=true`）；
- 采集适配器实现（TASK-M1-001/003）必须按 profile 分支取端点：模板类从 `repository`/`subject` 拼接，其余读 `discovery_url`。

## 回滚

还原 `schemas/source-registry.schema.json` 即可；该文件不参与数据库迁移，无数据影响。

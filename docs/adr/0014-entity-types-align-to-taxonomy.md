# ADR-0014：实体类型以 `config/taxonomy.yaml` 的 8 类为准

日期：2026-08-02
状态：已接受
关联：`AHR-DATA-300` §7、`config/taxonomy.yaml`、V004、V008

## 背景

M2 批量结构化过程中，1 条内容进入 `DEAD_LETTER`，错误为：

```
Input should be 'company', 'product', 'model', 'technology' or 'person'
[type=literal_error, input_value='organization']
```

排查发现两处规格对实体类型的定义不一致：

| 来源 | 定义 |
|---|---|
| `docs/spec/03-data-ingestion.md` §7 | 5 类：`company\|product\|model\|technology\|person` |
| `config/taxonomy.yaml` `entity_types` | 8 类：额外含 `organization`、`protocol`、`framework` |

`README.md` 的规范优先级为「领域专项文档 > `config/*.yaml`」，按此本应采用 5 类。但实际语料表明 5 类不足以覆盖 AI 行业的常见实体：

- `organization`：大学、标准组织、非营利研究机构（Allen Institute、LF AI、NIST）；
- `protocol`：MCP、OpenAI 兼容 API、A2A；
- `framework`：LangChain、vLLM、Transformers。

把这些强行归入 `company` 会产生错误事实——把大学标成公司，会污染 M3 的事件聚类与 M4 的实体过滤。

## 决策

**采用 `config/taxonomy.yaml` 的 8 类**，并同步：

1. `EnrichmentResult.entities[].type` 的 Literal 扩充为 8 类；
2. V008 迁移放宽 `entity.ck_entity_type` CHECK 约束；
3. Prompt 中的类型枚举同步更新；
4. 更新 `docs/spec/03-data-ingestion.md` §7 的示例，消除文档间冲突。

## 备选方案

- **保持 5 类并在 prompt 中要求归并**：否决。会稳定产生错误标注（大学 → 公司），且错误发生在数据层而非展示层，后续难以纠正。
- **保持现状不处理**：否决。当前失败率虽仅 1/700，但随着中文学术与标准组织类内容增加会上升，且失败是静默的（DEAD_LETTER 不告警）。

## 后果

- 实体标注更贴近真实语料，M3 聚类与 M4 实体过滤的输入质量提高；
- 已入库的 642 条结构化内容中，此前被迫归入 `company` 的组织类实体不会自动纠正，需在下次重跑 enrichment 时更新；
- `docs/spec/03` 与 `config/taxonomy.yaml` 之后必须同步修改，避免再次分叉。

## 回滚

还原 `schemas.py` 的 Literal 与 V008 迁移即可。已写入的 8 类数据在回滚后会违反 CHECK 约束，因此回滚前需先清理非 5 类的 `entity` 行。

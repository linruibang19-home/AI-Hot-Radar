# ADR-0022：用乱序前置迁移修复 V018 的空库安装

- 状态：已接受
- 日期：2026-08-11
- 相关：`AHR-SPEC-000` §8、`AHR-QSO-700` §2、`TASK-M5-001`

## 背景

发布基线的空库验收按文件顺序执行 V001–V021，在
`V018__vendor_entity_backfill.sql` 失败。V018 向 `vendor_entity` 写入
`zhipu`、`qwen` 等成员，但这些父级 `vendor` 行只会在运行期执行
`ahr.cli seed-topics` 后出现；全新数据库在 Flyway 阶段还没有它们，因此违反外键。

现有开发数据库已经执行 V018，并在 `flyway_schema_history` 记录了 checksum。
直接修改 V018 会使所有现有数据库在下次启动时校验失败，不能作为修复方案。

## 决策

新增 `V017_1__vendor_parents_for_backfill.sql`，只插入 V018 实际引用的八个
vendor 父记录，并使用 `ON CONFLICT (slug) DO NOTHING`。同时启用
`spring.flyway.out-of-order`：

- 新数据库按 V017 → V017.1 → V018 执行，V018 的外键前置条件成立；
- 已在 V021 的数据库会补执行 V017.1；已有 vendor 行全部冲突并保持原值；
- V018 及其他历史迁移的 checksum 不变。

运行期 `seed-topics` 仍是 vendor 展示元数据和完整成员关系的来源；V017.1 只负责
迁移依赖，不替代 taxonomy 同步。

## 备选

1. **直接修改 V018**：否决，会破坏已执行迁移的 checksum。
2. **新增 V022 再修复**：否决，空库在 V018 已失败，永远到不了 V022。
3. **移除 `vendor_entity.vendor_slug` 外键**：否决，会削弱数据完整性，且与问题无关。
4. **要求部署脚本在 Flyway 中途运行 `seed-topics`**：否决，迁移不再自包含，
   Java/Flyway、CI 和手工恢复会产生不同顺序。

## 后果

- Flyway 允许补执行低于当前 schema version 的已解析迁移；新增此类迁移必须保持
  幂等，并在空库和已有库两条路径上验证。
- vendor 父记录在全新数据库迁移后已经存在，但完整名称、描述、顺序和成员仍由
  `ahr.cli seed-topics` 收敛。
- CI 的空库门禁能够直接发现未来数据迁移的前置条件缺失。

## 回滚

保留 V017.1 的历史记录和数据，不删除已执行迁移。若不再需要乱序迁移，可在所有
受支持数据库均确认已执行 V017.1 后，通过后续配置变更关闭 `out-of-order`；不得删除
或改写 V017.1。

# ADR-0031：`content_chunk` 以不可变 chunk set 版本化

- 状态：接受
- 日期：2026-08-13
- 关联：ADR-0016、ADR-0021、ADR-0029、TASK-M5-017

## 背景

`rag_citation.content_chunk_id` 绑定物理证据行，这是历史答案可复核的基础。旧的重切块实现先
删除同 revision 的全部 chunk 再插入新行；一旦某个 chunk 已被引用，外键会拒绝删除。绕过
外键会让历史答案失去证据，而原地改写 chunk 又会把旧引用悄悄指向一段不同的文本。

同一原文 revision 的切块规则可以升级，但“原文版本”和“切块版本”不是同一个生命周期。

## 决策

1. `content_chunk` 增加 `chunk_set_id` 和 `is_active`。同一次切块产生的所有行共享一个
   `chunk_set_id`；每个 revision 同时只有一个 active set。
2. 重切块不删除、不改写旧行：在同一事务中退役旧 set，再插入一个全新的 active set。
3. 在线 dense、sparse、temporal 检索、embedding 回填和语料健康统计只读取 active chunk。
4. 历史 `rag_citation` 仍按 chunk 主键读取退役行；parent expansion 只扩展命中行所属的同一
   `chunk_set_id`，不能把两代 chunk 拼在一起。
5. 旧行不立即物理清理。只有在确认不存在 citation、retrieval trace 或其他审计引用后，才可由
   独立 retention 任务删除；本 ADR 不授权该清理。

## 备选

- **级联删除引用**：破坏历史答案可核验性，拒绝。
- **原地更新 chunk 文本**：同一 ID 的证据语义发生变化，拒绝。
- **复制 content revision**：正文没有变化却制造新 revision，混淆“来源内容变化”和“处理规则
  变化”，拒绝。

## 后果

- 重切块与历史引用可以同时成立；重切后检索立即只看到新 set。
- 物理 chunk 数包含退役证据，运维指标必须明确 active 与 retained，不能把总行数冒充当前索引。
- 每次重切会暂时增加存储，但范围可审计，且文本/向量规模远小于丢失证据的代价。

## 回滚

应用回滚时旧代码会忽略 `is_active`，因此数据库迁移不可单独回滚到旧检索代码。若必须回滚，
应回滚到支持 chunk set 的上一应用镜像，并保持 V026；不得删除仍被引用的退役行。

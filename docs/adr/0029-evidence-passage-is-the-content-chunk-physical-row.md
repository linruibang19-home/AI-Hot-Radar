# ADR-0029：逻辑 Evidence Passage 由 `content_chunk` 物理行承载

- 状态：接受
- 日期：2026-08-12
- 关联：AHR-SPEC-000 §7、AHR-DATA-300、AHR-RAG-400、ADR-0016、ADR-0021、TASK-M5-014

## 背景

规格使用 `evidence_passage` 表达“可被引用、能定位回原文的证据段”，早期数据模型表格还把它
写成独立表，并同时列出 `embedding_record`。当前 Flyway 物理模型没有这两张表：正文段落、
标题路径、顺序、token 数、搜索向量和 1024 维 embedding 都在 `content_chunk`；
`rag_citation.content_chunk_id` 直接绑定该行。父块根据同 revision 的相邻 chunk 动态展开，
不额外物化。

逻辑概念本身仍然成立，但如果把逻辑名当作表名，代码走读、SQL 调试和面试白板都会失真。

## 决策

1. `evidence passage` 保留为领域术语，表示“最终支持一个答案主张的原文证据段”。
2. 当前物理实现统一为 `content_chunk`：它持有段落文本、定位信息、FTS、embedding 与处理版本。
3. `embedding record` 是逻辑能力而非独立实体；当前向量与 chunk 同行，模型和处理版本用于判断
   是否需要回填。未来若多模型并存导致同行无法表达，再通过 ADR 和 Flyway 拆表。
4. 引用必须绑定 child chunk。自适应 parent block 只为生成补上下文，不能替换精确引用目标。
5. 规格中的实体表必须同时标注“领域名称”和“当前物理表”，禁止把未来候选表写成已存在。

## 备选

- **新增 `evidence_passage` 表**：制造与 `content_chunk` 的同步问题，没有新业务语义。
- **新增 `embedding_record` 表**：单 embedding 模型下增加 join 与一致性成本，收益不足。
- **废弃 Evidence Passage 术语**：会丢失领域层“证据而非任意切块”的重要约束。

## 后果

- 业务语言和数据库实现都能被准确讲清；代码、SQL、引用 API 使用同一主键。
- 多 embedding 模型并存仍是未来能力，不能通过 UI 任意切换而跳过全库回填与评测。

## 回滚

若未来需要独立证据生命周期或多模型向量表，通过新 ADR、双写回填、引用兼容与 Flyway
迁移实施；不得直接重命名或删除现有 `content_chunk`。

# 评测存档

M4 检索与生成侧评测的原始产物。每一轮一份逐题 JSON。

**叙述部分已合并为一份** [RAG 调优实验纪要](../../docs/status/evidence/rag-tuning-log.md)：B1–B15、生成侧与延迟的
改动、指标变化和结论都在里面，包含两个负结果。下表保留 JSON 与轮次的对应关系。

**这里的文件是证据，不是缓存。** 站内 `/eval` 页展示的是
`scripts/build_eval_summary.py` 从这些 JSON 生成的摘要；摘要可以重新生成，
JSON 不能——它们记录的是当时那个语料、那份配置跑出来的结果。

```bash
python scripts/build_eval_summary.py
```

## 检索轮次

| 轮次 | JSON | 报告 | 结论 |
|---|---|---|---|
| B1 | `m4-rag-eval-B1-20260803.json` | [B1](../../docs/status/evidence/rag-tuning-log.md) | 纯稠密基线 |
| B2 | `m4-rag-eval-B2-union-20260803.json`<br>`m4-rag-eval-B2-sparse-20260803.json` | [B2](../../docs/status/evidence/rag-tuning-log.md) | **负结果**：并集比纯稠密还差 |
| B3 | `m4-rag-eval-B3-rrf-20260803.json` | [B3](../../docs/status/evidence/rag-tuning-log.md) | RRF + 时间过滤 |
| B4 | `m4-rag-eval-B4-rerank40-20260803.json`<br>`m4-rag-eval-B4-rerank100-20260803.json` | [B4](../../docs/status/evidence/rag-tuning-log.md) | 重排达标，40 候选优于 100 |
| B7 | `m4-rag-eval-B7-20260804.json` | [B7](../../docs/status/evidence/rag-tuning-log.md) | 时效融合 |
| B8 | `m4-rag-eval-B8-incumbent-20260804.json`<br>`m4-rag-eval-B8-swept-20260804.json` | [B8](../../docs/status/evidence/rag-tuning-log.md) | **负结果**：42 组权重，结论是不改 |
| B9 | `m4-rag-eval-B9-20260804.json` | [B9](../../docs/status/evidence/rag-tuning-log.md) | directness / source_fit |
| B10 | `m4-rag-eval-B10-20260804.json` | [B10](../../docs/status/evidence/rag-tuning-log.md) | entity_subject / repost |
| B12 | `m4-rag-eval-B12-depth40-20260807.json`<br>`m4-rag-eval-B12-depth20-20260807.json` | — | 自适应重排深度 |
| B13 | `m4-rag-eval-B13-20260807.json` | — | **负结果**：中文 bigram 端到端 ±0.0000 |
| B15 | `m4-rag-eval-B15-20260809.json` | [B15](../../docs/status/evidence/rag-tuning-log.md) | IDF + 实体加权在 ±0.02 噪声内，不能声称提升 |
| ENTITY | `m4-rag-eval-ENTITY-20260810.json` | [产品成熟度复核](../../docs/status/evidence/rag-product-readiness-20260810.md) | 在线时间通道对齐、实体时间通道与来源多样性诊断（B3，无重排） |
| B9-FINAL | `m4-rag-eval-B9-FINAL-20260811.json` | [专项发布审计](../../docs/status/evidence/rag-specialist-audit-20260811.md) | 90 题完整重排发布回归，Recall@20 0.8994 |
| SPECIALIST | `m4-rag-eval-SPECIALIST-20260811.json` | [专项发布审计](../../docs/status/evidence/rag-specialist-audit-20260811.md) | 15 题同快照实体/噪声 A/B；Recall@20 0.9333，噪声无退化 |
| **B9-RELEASE** | `m4-rag-eval-B9-RELEASE-20260924.json` | [调优纪要](../../docs/status/evidence/rag-tuning-log.md) | **v0.1.30 发布快照（检索）**：重排 40 候选（生产深度），Recall@20 0.8998，重排失败 0 |
| **SPECIALIST-RELEASE** | `m4-rag-eval-SPECIALIST-RELEASE-20260924.json` | [调优纪要](../../docs/status/evidence/rag-tuning-log.md) | **v0.1.30 发布快照（专项）**：15 题 entity / noise Recall@20 0.9333 / 0.9333，通过 |
| SPECIALIST-IDENTIFIER | `m4-rag-eval-SPECIALIST-IDENTIFIER-20260811.json` | [专项发布审计](../../docs/status/evidence/rag-specialist-audit-20260811.md) | **负结果**：扩大深度/identifier 未救回第 27 名目标，未上线 |

## 生成侧与延迟

| 轮次 | JSON | 报告 | 结论 |
|---|---|---|---|
| GEN（08-04） | `m4-rag-eval-GEN-20260804.json` | [GEN](../../docs/status/evidence/rag-tuning-log.md) | 首次生成侧评测 |
| GEN（08-07） | `m4-rag-eval-GEN-20260807.json` | — | 管线改动后重跑，**未接判官** |
| GEN（08-07 判官轮） | `m4-rag-eval-GEN-20260807-judged.json` | — | 加入拒答判官；暴露误拒率 7.69% |
| GEN-FIX（08-07） | `m4-rag-eval-GEN-20260807-fixed.json` | — | 修掉解析失败分支丢答案，误拒率 **0.00%** |
| LAT | `m4-rag-eval-LAT-20260804.json` | [LAT](../../docs/status/evidence/rag-tuning-log.md) | 99% 的延迟在三次外部往返 |
| GEN（08-09 门控） | `m4-rag-eval-GEN-20260809-gated.json` | [门控回归](../../docs/status/evidence/rag-tuning-log.md) | 支持度达标率 0.9596，误拒率不变 |
| GEN（08-09 双口径） | `m4-rag-eval-GEN-20260809-dual.json` | [双口径说明](../../docs/status/evidence/rag-tuning-log.md) | 段落级 0.9371；父块级 1.0000 是门控结果，不作独立判据 |
| GENERATION-FINAL | `m4-rag-eval-GENERATION-FINAL-20260811.json` | [专项发布审计](../../docs/status/evidence/rag-specialist-audit-20260811.md) | 90 题：完整性 0.9881，段落支持达标率 0.9344，拒答准确率 1.0000 |
| SPECIALIST-FINAL2 | `m4-rag-eval-SPECIALIST-FINAL2-20260811.json` | [专项发布审计](../../docs/status/evidence/rag-specialist-audit-20260811.md) | 15 题生成与人工 P0 审计；14 答、1 个已知缺口安全拒答 |
| **GENERATION-RELEASE** | `m4-rag-eval-GENERATION-RELEASE-20260924.json` | [调优纪要](../../docs/status/evidence/rag-tuning-log.md) | **v0.1.30 发布快照（生成）**：首个按提问时间冻结语料的发布轮。完整性 1.0000，段落支持 0.9900（每条引用），逐句 0.9319 / 0.9382（631 对），误拒 1/78，诱导题 0/12；deepseek-v4-flash 由 DeepSeek-V4.1-Flash 提供服务 |
| POST-FINALIZER | `m4-rag-eval-POST-FINALIZER-RAG009-20260811.json` 等 4 份 | [专项发布审计](../../docs/status/evidence/rag-specialist-audit-20260811.md) | 支持度过滤后的逐句门禁真实重放，4/4 完整性 1.0000 |

## 诊断运行（非发布）

| 轮次 | JSON | 结论 |
|---|---|---|
| GEN-FROZEN（09-24，本地） | `m4-rag-eval-GEN-FROZEN-20260924.json` | **首个按提问时间冻结语料的生成评测**，此后的生成侧对比以它为基线。引用准确率 0.6888（与未冻结的 NUMAUDIT 逐题配对 +0.124）；273 个被引（题, 条目）无一晚于提问时间；逐条记录引用，可离线重打分 |
| SENTENCE（09-24，本地） | `sentence-support-pairs-20260924.json` | FROZEN 全部 685 个句子–引用对，对父块、命中分块、每个兄弟分块的交叉编码器分数。逐句删除 23 句中至少 14 句原文有，删除不上线；按句选锚点段落级 0.8613 → 0.8993 |
| PLANNER-AB（09-24，本地） | `m4-rag-eval-PLANNER-AB-regex-20260924.json`<br>`m4-rag-eval-PLANNER-AB-llm-20260924.json` | 生产检索配置（重排 40 候选）上正则 vs LLM 规划器：R@20 0.8998 vs 0.8908，逐题 0 升 2 降；两轮重排失败均为 0。补上 B16 丢失的逐题数据 |
| AUDIT-AB（09-24，本地） | `audit-ab-golden-20260924.json`<br>`audit-ab-specialist-20260924.json` | ADR-0036 配对实验：同一草稿上新旧审计提示词各判一次，逐条保存草稿与两份输出。黄金集 31 次审计耗时均值 3875 → 998 ms；9 次分歧全是旧提示词拆句；专项集 5 次完全一致，P0 RAG-VENDOR-010 两边都改写 |
| SPARSE（09-24，本地） | `m4-rag-eval-SPARSE-20260924.json` | 纯稀疏通道复测（不带实体词）：纯中文 8 题 R@20 0.3438（B2 为 0），含英文 70 题 0.3231。逐版本拆解与带实体词的生产口径见[调优纪要](../../docs/status/evidence/rag-tuning-log.md)「ZH」一节 |
| NUMAUDIT（09-24，本地） | `m4-rag-eval-GEN-NUMAUDIT-20260924.json`<br>`m4-rag-eval-SPECIALIST-NUMAUDIT-20260924.json` | ADR-0034 回归：数值审计 44 次触发、改动 15 次、fail-closed 0；生成评测未冻结语料，与发布基线的其余差异不可比 |

## 没有出现在 `/eval` 上的几份，以及为什么留着

站内摘要只展示能构成一条趋势线的轮次。下面这些不在其中，但都是真实产物，
删掉就等于把「当时确实这么跑过」抹掉：

- **`m4-rag-eval-B11-20260804.json`** —— B11 与 B10 在检索指标上无差别，
  没有独立结论可讲，因此没有进趋势表。
- **`m4-rag-eval-SWEEP-20260804.json`** —— B8 那一轮 42 组权重的**全量**扫描输出；
  `/eval` 上引用的是它的两个代表点（现行 vs 网格最优）。
- **`m4-rag-eval-B4-rerank40-20260804.json`** —— 零分块修复**之后**重跑的 B4。
  趋势表用的是 08-03 那份，因为同一行必须和相邻行同语料才可比；
  这一份是「修完语料再看一眼」的对照。
- **`m4-rag-eval-GEN-20260807.json`** —— 判官接上**之前**的那次重跑。
  判官轮的结论正是「旧指标测的是形式不是正确性」，所以旧指标那一次得留着当对照。
- **`m4-rag-eval-GEN-20260804.json`** —— 08-04 的生成侧基线，三轮对比表里的第一列。

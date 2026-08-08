# 评测存档

M4 检索与生成侧评测的原始产物。每一轮一份逐题 JSON，重要的轮次另有一份长文报告。

**这里的文件是证据，不是缓存。** 站内 `/eval` 页展示的是
`scripts/build_eval_summary.py` 从这些 JSON 生成的摘要；摘要可以重新生成，
JSON 不能——它们记录的是当时那个语料、那份配置跑出来的结果。

```bash
python scripts/build_eval_summary.py
```

## 检索轮次

| 轮次 | JSON | 报告 | 结论 |
|---|---|---|---|
| B1 | `m4-rag-eval-B1-20260803.json` | [B1](m4-rag-eval-B1.md) | 纯稠密基线 |
| B2 | `m4-rag-eval-B2-union-20260803.json`<br>`m4-rag-eval-B2-sparse-20260803.json` | [B2](m4-rag-eval-B2.md) | **负结果**：并集比纯稠密还差 |
| B3 | `m4-rag-eval-B3-rrf-20260803.json` | [B3](m4-rag-eval-B3.md) | RRF + 时间过滤 |
| B4 | `m4-rag-eval-B4-rerank40-20260803.json`<br>`m4-rag-eval-B4-rerank100-20260803.json` | [B4](m4-rag-eval-B4.md) | 重排达标，40 候选优于 100 |
| B7 | `m4-rag-eval-B7-20260804.json` | [B7](m4-rag-eval-B7.md) | 时效融合 |
| B8 | `m4-rag-eval-B8-incumbent-20260804.json`<br>`m4-rag-eval-B8-swept-20260804.json` | [B8](m4-rag-eval-B8.md) | **负结果**：42 组权重，结论是不改 |
| B9 | `m4-rag-eval-B9-20260804.json` | [B9](m4-rag-eval-B9.md) | directness / source_fit |
| B10 | `m4-rag-eval-B10-20260804.json` | [B10](m4-rag-eval-B10.md) | entity_subject / repost |
| B12 | `m4-rag-eval-B12-depth40-20260807.json`<br>`m4-rag-eval-B12-depth20-20260807.json` | — | 自适应重排深度 |
| B13 | `m4-rag-eval-B13-20260807.json` | — | **负结果**：中文 bigram 端到端 ±0.0000 |

## 生成侧与延迟

| 轮次 | JSON | 报告 | 结论 |
|---|---|---|---|
| GEN（08-04） | `m4-rag-eval-GEN-20260804.json` | [GEN](m4-rag-eval-GEN.md) | 首次生成侧评测 |
| GEN（08-07） | `m4-rag-eval-GEN-20260807.json` | — | 管线改动后重跑，**未接判官** |
| GEN（08-07 判官轮） | `m4-rag-eval-GEN-20260807-judged.json` | — | 加入拒答判官；暴露误拒率 7.69% |
| GEN-FIX（08-07） | `m4-rag-eval-GEN-20260807-fixed.json` | — | 修掉解析失败分支丢答案，误拒率 **0.00%** |
| LAT | `m4-rag-eval-LAT-20260804.json` | [LAT](m4-rag-eval-LAT.md) | 99% 的延迟在三次外部往返 |

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

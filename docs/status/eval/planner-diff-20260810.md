# Planner 对照：正则 0.6667 vs LLM 0.9067

逐题数据：[planner-diff-20260810.json](planner-diff-20260810.json)
被测：`rag/planner.py`（六条正则）对 `rag/llm_planner.py`（self-query，deepseek-chat）

## 我之前说「缺标注所以不可判定」是错的

上一轮把 `AHR-QSO-700` §8 的 planner accuracy 记为 ⬜ 不可判定，理由是黄金集没有
`expected_query_type`。**这个判断没去看黄金集的结构。**

黄金集按六个文件组织，每个文件头写着 `category:`，而其中五个值
（`recent_updates` / `timeline` / `comparison` / `fact_check` / `explainer`）
**与 `QUERY_TYPES` 逐字相同**。写题的人在把一道题放进 `02-timeline.yaml` 时，
就是在判断「这是一道时间线问题」——那正是要标注的东西，只是没叫这个名字。

**排除 `abstention` 的 15 题**：那一类按**用途**分组（考拒答），不按问法分组，
一道诱导题可以写成任何句式，所以它不携带 query_type 期望。
`recommendation` 没有对应类别，因此这套代理覆盖 75/90 题。

> **这是代理不是标注**，差别要说清楚：`category` 是为了分组评测而标的，
> 不是为了标注 planner 而标的。两者在这五类上重合得很好，但若要把它写进
> `expected_query_type` 长期使用，应当由人确认一遍而不是我直接灌进去。

## 结果

| | 题数 | 正则 | LLM |
|---|---:|---:|---:|
| **总体** | 75 | **0.6667** | **0.9067** |
| recent_updates | 15 | 1.00 | 1.00 |
| explainer | 15 | 1.00 | 1.00 |
| timeline | 15 | 0.40 | 0.60 |
| comparison | 15 | 0.47 | 0.93 |
| fact_check | 15 | 0.47 | 1.00 |

**LLM 版 0.9067 越过了 §8 的 ≥0.90 门槛，正则版 0.6667 差得很远。**

### 正则那个 1.00 是假的

`explainer` 两边都是 1.00，但对正则来说这是**兜底类**：任何六条正则都不匹配的问题
一律判为 explainer，所以它在 explainer 上必然全对，代价是在别处全错。
34 条分歧里 **32 条是 `explainer → 其他`**：

```
explainer → fact_check      20 题
explainer → comparison       6 题
explainer → timeline         5 题
explainer → recent_updates   1 题
timeline  → recent_updates   1 题
recent_updates → comparison  1 题
```

**分歧精确地堆在兜底类上**，这正是「加一条正则只修一个短语，修不了这个类」的形状。

### 时间窗

正则有窗口而 LLM 判无窗口：**0 题**；反过来 2 题。
LLM 没有出现「把解释型问题套上七天窗口」这种错误，
也没有把该有窗口的问题判成无窗口——这一维两者都没有明显退化。

## 为什么还没有默认启用

三条，缺一不可：

1. **代理需要确认**。上面那条已经说了：`category` 作为期望值是合理的，但不是被
   当作 planner 标注写下来的。
2. **分类更准 ≠ 答案更好**。B8 记过融合序会被重排重写；同理，`query_type` 更准
   是否传导到 Recall/MRR，必须端到端跑一轮才知道。不跑就开等于用「它更聪明」
   代替证据。
3. **成本**。每个问题多一次模型往返，p50 约 10s 的链路上不可忽略，
   而收益尚未量化（见第 2 条）。

`llm_planner` 已实现、已测（12 个用例）、**默认关闭**，
任何失败/超时/无法解析都回落到正则 planner——planner 在每个问题的关键路径上，
供应商抖动只能损失精度，不能损失答案。

## 下一步

1. 人工确认 `category` 可作为 `expected_query_type`（或逐题微调），写进黄金集；
2. 以 LLM planner 开启跑一轮 B16，看分类提升是否传导到检索指标；
3. 若传导，再讨论成本与默认开关。

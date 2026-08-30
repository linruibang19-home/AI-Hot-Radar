# HTML 列表档位抽不到发布日期 · 2026-08-30

调查记录，**未修**。先写下来是因为最省事的那个修法（直接回填）会把语料改坏，
而这一点只有量过才知道。

## 现象

`static_listing_to_article` 档位 **489 条内容里 488 条 `published_at` 为 NULL**（99.8%）。

| profile | 无日期 / 总数 |
|---|---|
| static_listing_to_article | 488 / 489 |
| docs_changelog | 114 / 325 |
| dynamic_listing_to_article | 12 / 12 |
| public_json_api | 7 / 133 |
| rss_to_article | **6 / 915** |

RSS 几乎不出问题（0.7%）——协议自带日期。HTML 列表要靠从文章页里抽，而它没抽到。

全库 3327 条里 627 条无发布日期，占 18.8%。

## 为什么这件事重要

检索按 `COALESCE(published_at, observed_at)` 裁时间窗。没有发布日期时，
**首见日期顶替上去**——于是一篇 2024 年的旧稿，只要今天才被抓到，就落在"最近一周"里。

这直接打在最常见的问题类型上：19 道新标注题里 11 道是 `recent_updates`。
RAG-GOLD-097「最近grok有什么动态吗」里那四条 grade 1（Grok-2 测试版、Grok-1.5V、
B 轮融资）就是这么进来的。

## 最省事的修法会把语料改坏

直觉方案是「对 `published_at IS NULL` 的条目重抽一遍日期」。实测三个页面：

| 抽取结果 | 实际发布 | 页面 |
|---|---|---|
| 2023-11-03 | 2026-08-01 | anthropic.com/news/claude-opus-5 |
| 2023-11-03 | 2026-08-01 | anthropic.com/news/claude-sonnet-5 |
| 2026-08-12 | 2026-08-12 | x.ai/news/grok-4-6 |

**Anthropic Newsroom 每一页都抽出同一个 2023-11-03**，差了将近三年。
JSON-LD 在这些页面上没有 `datePublished`，于是 `extract_article` 回落到
trafilatura 的 `metadata.date`，而它取到的是站点级的东西（页脚或政策日期），
不是这篇文章的发布日期。

xAI 那一条 JSON-LD 有日期，抽得准。

所以：**回填会把 Anthropic 全部条目写成 2023-11-03**。当前的 NULL 至少会回落到
首见日期，方向是对的；写进一个错日期比留空更糟，因为它看起来是确定的。

已有 110 条内容的 `published_at` 比 `observed_at` 早一年以上——其中一部分是合理的
（2025 年的模型卡 2026 年才抓到），但错日期就藏在这个人群里。

## 修之前要先有的东西

1. **一个合理性判据**。「站点级常量」是这次的特征：同一信源的多个条目抽出同一个日期，
   那就不是发布日期。这个判断需要跨条目的状态，`extract_article` 现在拿不到。
2. **抽样量一遍**，而不是照着三个样本改。要知道 trafilatura 回落路径在
   `static_listing_to_article` 的 22 个信源上的实际正确率，再决定是收紧它还是关掉它。
3. 关掉之后仍然抽不到日期的信源（Anthropic、Together AI 的页面里确实没有任何日期信号），
   要么接受首见日期并在界面上说清楚，要么从列表页拿日期。

## 与已知模式的关系

同一个家族：**空值和"安静的一周"长得一模一样，系统默认信后者。**
参见同日修掉的 `docs_changelog` 两个缺陷
（[golden-refresh-20260830.md](golden-refresh-20260830.md)）——
那次是 `SUCCESS + discovered 0` 被当成健康，这次是 `published_at IS NULL`
被当成"就是今天发的"。

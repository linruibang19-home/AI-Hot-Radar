# 黄金集刷新 · 第二步（标注）· 2026-08-30

四步计划的第二步。第一步（挖候选、出工作表）见上一次提交；这次把 30 个候选
标完，并在标注过程中修掉了三个会让结果失真的缺陷。

## 结果

`data/golden/pending/worksheet-20260830.yaml` —— **19 题**，74 个打了分的文档
（grade 2 共 43 个，grade 1 共 31 个），11 题剔除并逐条记了原因。

| 类别 | 题数 |
|---|---|
| recent_updates | 11 |
| abstention | 6 |
| timeline | 2 |

`golden-validate` 通过（退出码 0）。19 题全部能被 `_parse_question` 解析，
74 个文档 id 全部在库、全部落在各自的快照窗口内，19 题都带了 planner 标注
（`expected_query_type` / `expected_time` / `expected_entities`）。

**标注方法是 `model_assisted`，还没有人工复核。** 文件头的 `annotation` 块
写明了这一点，以及三条看不见的东西：判据只有标题/信源/日期和 110 字摘录；
检索窗口外的漏召发现不了；类别分布本身有偏。复核之前，这批题跑出来的数字
不能和 90 题黄金集的历史数据并排比较。

被测的是 DeepSeek v4-flash（生成）加 bge-m3 / bge-reranker-v2-m3（检索），
标注的是另一个模型，所以不是「自己给自己判卷」。但共性偏差仍在，
所以定位是「省人力的初稿」而不是「等价于人工」。

## 标注过程中修掉的三个缺陷

### 1. 评测回放被当成了真实流量（影响最大）

每跑一次评测，90 道题都会走同样的流水线、写进同一张 `rag_query` 表。
**247 行里有 71 行（29%）是这么来的。**

于是挖矿把黄金集读回给了它自己：第一批 30 个候选里有 **6 个已经是黄金集里的题**——
RAG-GOLD-002 / 034 / 044 / 048 / 076 / 079。其中 076「Qwen4-Ultra 的参数量是多少？」
和 079「Anthropic 因为那三起事故被罚了多少钱？」是**拒答题**，
它们「支持度低」恰恰是因为系统拒答对了，却被 `weak_support` 挑出来当失败案例。

`candidates.mine` 新增 `exclude_questions`，CLI 用 `--golden` 加载黄金集并传进去，
结果里报 `golden_replays_skipped`（当前 71）。排除后 `weak_support` 从 21 降到 15。

### 2. 快照外的文档可以被标成相关

评测按 `asked_at` 裁快照，发布时间晚于提问时间的文档取不到。把这种文档标成
相关，就是记一笔任何检索改动都追不回的漏召。

这类文档真实存在：信源会在首次抓取之后把 `published_at` 往后改
（HF 模型卡作者更新 model card 就会）。**4823 条 trace 里有 109 条是这样**，
今天看到的日期不是提问当时的日期。已验证的一例：`8242ae25` 的
`published_at` 是 08-18，`observed_at` 是 08-04，而提问发生在 08-10。

工作表现在把这类文档标成「快照外」并**不给 `id` 行**——留在视野里（它确实是
漏斗看过的东西），但标不了。一题的候选全部落在快照外时另有提示。

### 3. `golden-validate` 比真实 schema 更严

原来要求 `answerable: false` 必须同时有 `presupposition` 和 `must_not_claim`。
但 RAG-GOLD-077 和 080 就没有 `must_not_claim`，是合法的。而且
`must_not_claim` 写错比不写更糟：它是子串匹配，会误伤那些正确点破前提、
因而必然提到该词的回答。

改成只要求 `presupposition`（拒答判分器读的就是它），新增 `category` 检查
（`data/golden/` 按类分文件，拆分需要它），校验范围收敛到 `questions:` 之后
（否则 `dropped:` 里保留的 `TODO-` id 会被误判成没填完）。

## 挖出来的东西

- **智谱答不出来**（当时判断为覆盖缺口，**是错的**，见下节）。三道同义提问
  （08-09 一次、08-10 两次）都答不出来，唯一沾边的是第三方对 GLM-5.2 的量化重打包。
  留 RAG-GOLD-100 一道记这个失败。
- **词形命中不等于实体命中**：「Cursor 最近有什么产品更新？」引了 LiteLLM /
  Mastra / CrewAI / Langfuse，另有一条 Qwen 微调模型的摘录写着
  "A blinking cursor that mocks you"——稀疏通道匹配的是「光标」这个名词。
  90 题里没有一道覆盖这个失败模式。
- **信源回填旧稿**：xAI 把 Grok-2 测试版、Grok-1.5V、B 轮融资这些 2024 年的旧稿
  按 2026-08-02 回填进来了。时间窗正确但内容陈旧，RAG-GOLD-097 记着这四条。
- **时间窗没参与排序**：「2026 年 8 月这一周 Anthropic 有什么动作？」窗内只有
  1 篇，检索捞回 18 篇（其余全在 08-11~08-19），唯一在窗内的那篇排到第 17 位、
  因预算已满被丢掉。
- **类别分布与手写题集完全不同**：真实流量几乎只问「最近 X 有什么动态」
  （19 题里 11 题），而 90 题是六类各 15 道均分的。两边一比就能看出手写题集
  假设的用户和真实用户不是同一批人。

## 为什么召回的东西对不上问题（同日追加）

不是某个通道调坏了，是**整条检索链路没有「不合格」这个概念**：

| 阶段 | 代码 | 有没有绝对门槛 |
|---|---|---|
| 稠密 | `ORDER BY ch.embedding <=> %s LIMIT %s` | 无 |
| 稀疏 | `ORDER BY rank DESC LIMIT %s` | 无 |
| RRF 融合 | `weight / (k + rank)` —— **按名次算，分数丢掉** | 无 |
| §6 加权 | `(score - low) / spread` —— **min-max 归一化** | 无 |
| 重排 | 取 `top_n`，分数只用来排序 | 无 |
| 证据筛选 | 每篇 ≤2、每源 ≤3、预算 10 | 无 |

第四行是关键：归一化之后，**每次结果里最差的那条永远是 0.0、最好的永远是 1.0**，
跟它们究竟好不好没有关系。于是任何问题都会返回 10 条；语料里没有的时候，
返回的就是「最不差的 10 条」。生成侧被告知「依据这些证据回答」，它就照办了。

实体约束也不是过滤器——`BOOST_ENTITY_SUBJECT = 0.05` 是个加分项，
压不住一条各方面都更像的无关文档。所以「Cursor 最近有什么产品更新？」
能引到 CrewAI 的 release，「codex近段的额度调整新闻」能引到 Deepseek 涨价。

### 一个绝对分数确实活了下来

交叉编码器的 top-1 打分。对 15 道有 trace 的已标注题测：

| | 中位 | 区间 |
|---|---|---|
| top-1 重排分 · 不可答 6 题 | 0.076 | 0.016 – 0.980 |
| top-1 重排分 · 可答 9 题 | 0.901 | 0.274 – 0.986 |
| top-1 稠密分 · 不可答 | 0.577 | 0.534 – 0.613 |
| top-1 稠密分 · 可答 | 0.625 | 0.546 – 0.767 |

**稠密相似度基本没有信号**（两组区间几乎完全重叠），交叉编码器有。
阈值 0.15 时挡下 4/6 不可答题、误伤 0/9 可答题。

**但它挡不住前提为假的问题。** 全样本最高分 0.9800 是
「DeepSeek 在 2026 年 8 月收购 OpenAI 的细节是什么？」——语料里满是 DeepSeek、
满是 OpenAI、满是收购，话题相关性拉满。交叉编码器测的是相关不是真假。
所以两种失败模式要分开治：

- **语料没有** → 相关性地板能拦（元问题、信源覆盖缺口）
- **前提为假** → 只能靠支持度门禁和拒答判官，地板一点用没有

### 这次只记录，不设门禁

`metrics.retrieval_confidence` 落库并显示在问答页漏斗的「最强证据得分」一行。
不设阈值的理由和 `support.is_weak_retrieval` 一样，也和本会话前面那次教训一样：
n=15 是假设不是阈值，误拒率是这个系统最贵的指标，
真正有资格定这个数的是第三步的双轨评测。

## 修正：智谱那题不是覆盖缺口，是采集缺陷（同日追加）

我上面写「信源库里没有智谱 / Z.ai 的官方源」，**这是错的**。去查配置才发现
`glm-new-releases` 一直配着、`enabled`、`ACTIVE`、连续失败 0、最近一次成功 08-28
——**而库里只有 1 条内容**。

顺着查下去挖出两个缺陷，第二个把整个 `docs_changelog` 档位废掉了。

### 缺陷 A：游标把没入库的东西记成已见

`pipeline.py` 保存游标那段的注释一直写着「only content that actually committed
is treated as seen」，实现却是 `isinstance(adapter, HtmlListingAdapter)` ——
**七个适配器里只对一个成立**。`docs_changelog` 同样带 seen-set，却不在其中：
`discover` 返回整页解析出的全部段落，主循环只取 `batch.items[:max_documents]`
（默认 5），游标却把**全部**哈希存了回去。DeepSeek 的 changelog 解析出 21 段、
入库 1 段、另外 20 段永久沉到游标后面。此后每次轮询都是 SUCCESS + discovered 0。

改成由适配器自己回答 `cursor_for_committed(...)`，两个带 seen-set 的适配器各实现一份。

### 缺陷 B：fragment 被当成装饰丢掉，而它就是身份

`canonicalize_url` 里那行注释说「Fragments never identify a distinct server-side
document」——对文章成立，对 changelog 不成立：每条都是同一页面的一个 `#锚点`。
丢掉 fragment 之后 26 条发布哈希成同一个 URL，`content_item_canonical_url_hash_key`
唯一索引留下第一条、拒绝其余全部。而失败是静默的：`UniqueViolation` 被
「一篇坏页面不能拖垮整轮」的 `except Exception` 吞掉，run 依然 SUCCESS，
`discovered_count` 还是真实段落数。

**12 个 `docs_changelog` 信源，每个恰好 1 条内容**，游标合计声称见过 406 段。

改法：`canonicalize_url(url, keep_fragment=True)`，只在 `persist_document` 里
按 `source.profile == "docs_changelog"` 打开，通用规则不动。

### 缺陷 C：智谱页面本身抽不出来（顺带）

`docs.bigmodel.cn` 的 HTML 是 2.2MB 框架包着 6KB 文字，trafilatura 只还回一段
「公告通知」。同站为机器读者提供了 `.md` 版，每条发布是
`<Update label="2026-08-26" description="GLM-5.3-Flash 原生多模态模型上线">`
——带日期、带标题、可切分。改指 `.md` 并让适配器识别 MDX `<Update>` 块，
切出 **26 条发布，26 条都有发布日期**。

顺手修掉一个潜伏问题：纯中文标题 slug 化后是空串，旧代码回退到循环下标，
于是页面顶部加一条新发布就会让下面每一条改名重新入库。改成对标题取哈希。

### 结果

| | 修复前 | 修复后 |
|---|---|---|
| `docs_changelog` 全档位内容数 | 11 | **325** |
| gemini-api-changelog | 1 | 60 |
| anthropic-app-release-notes | 1 | 53 |
| mistral-changelog | 1 | 50 |
| openai-deprecations | 1 | 44 |
| glm-new-releases | 1 | 27（26 条带日期） |
| deepseek-api-changelog | 1 | 14 |

还没修好的三个：`anthropic-api-release-notes`、`openai-codex-changelog` 仍是 1 条，
`anthropic-claude-code-changelog` 是 0 条 —— 另一种原因，待查。
`mistral` / `openai-api-changelog` / `deepseek` 有内容但 `published_at` 全空：
它们的标题只有版本号没有日期，按规格不许编造日期，所以只有 `observed_at`。

### 这对 RAG-GOLD-100 的影响

提问发生在 08-10，当时语料里确实没有这些文档，所以 `answerable: false`
对那个快照成立。但**理由要改**，而且修好之后该重跑这题——它很可能变成可答题，
那本身就是这条修复的验收。工作表里的 notes 已经改过。

### 还欠一个信号

`qwen-research` 至今是纯 SPA（90KB HTML、0 个 `<a>`、4 个字），已停用。
但它「SUCCESS + HTTP 200 + discovered 0 + 0 条内容」绿了好几周没人发现，
和上面两个缺陷是同一个形状：**连续多次 discovered 0 不该算健康**。
这个信号还没做。

## 下一步

第三步：评测跑双轨（`rag-eval --set regression|fresh`）。前置条件是人工复核这 19 题
——在此之前 fresh 集只能观察、不能设阈值。第四步：把轮换规则写进 ADR。

## 验证

- `1047 passed`（新增 10 条：worksheet 8 条、candidates 2 条）
- `ahr golden-validate data/golden/pending/worksheet-20260830.yaml` → 退出码 0

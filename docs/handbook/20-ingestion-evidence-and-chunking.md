# 20｜从不同信源到可引用切块：入库、版本与多模态边界

本文回答三个经常被混在一起的问题：系统采到了什么、数据库保存了什么、RAG 最终检索的又是什么。
描述以当前 Python 采集代码、Flyway 表结构与 2026-08-15 本地数据库抽样为准；动态数量只是带日期的观察值，不是长期承诺。

## 1. 一条内容在系统里的五层身份

```text
公开信源
  │  RSS/API/列表只负责发现候选，或直接提供可验证的完整正文
  ▼
raw_document                原始 HTTP 响应审计副本
  │
  ▼
content_item                稳定业务身份：同一 URL/外部 ID 的“这篇内容”
  │ 1:N
  ▼
content_revision            一次不可变正文版本：抽取后的 Markdown/纯文本
  │ 1:N
  ▼
content_chunk               一次切分得到的物理证据段，FTS 与向量都挂在这里
  │
  ▼
rag_citation                已生成答案对物理 chunk 的引用，不回指 AI 摘要
```

这五层不能合成一张表：抓取响应会重试，正文会修订，item 身份要稳定，chunk 会因算法升级重切，而已经发出的引用必须继续指向当时的物理证据。

## 2. 数据库里分别长什么样

### 2.1 `raw_document`：保留“当时服务器返回了什么”

典型字段包括 `source_id`、`crawl_run_id`、`requested_url`、`final_url`、`canonical_url`、
`status_code`、响应头、`content_type`、原始 `body_bytes`/哈希、`fetched_at` 与 parser 版本。

它解决的是可审计和重放，不直接给网页或 RAG 使用。即使正文门禁拒绝这次响应，抓取事实仍可保留；反过来，门禁拒绝的响应不会创建可检索内容。

### 2.2 `content_item`：稳定业务身份与发布投影

简化后的记录可以理解为：

```yaml
id: <稳定 UUID>
source_id: <来源 UUID>
external_id: "llama.cpp release tag / RSS guid / arXiv id"
canonical_url: "https://..."
original_title: "上游标题"
published_at: "上游发布时间"
current_revision_id: <当前正文版本>
enrichment_state: ENRICHED | PENDING | FAILED | SKIPPED
zh_title: "经 schema 校验的中文标题"
summary_zh: "经 schema 校验的中文摘要"
content_type: model_release | research | ...
```

`zh_title` 和 `summary_zh` 是展示与召回辅助字段，不是最终证据。当前公开列表只展示已完成中文结构化且字段非空的 `ENRICHED` 项；待处理英文原文不会再直接泄露到中文公共列表。

### 2.3 `content_revision`：真正被切分的正文版本

关键字段是 `content_item_id`、`raw_document_id`、`revision_no`、`title`、
`body_markdown`、`body_text`、`excerpt`、`discovery_summary`、正文哈希、抽取器与版本、质量分和门禁结论。

- `body_text` / `body_markdown` 才是 RAG 切分输入；
- `discovery_summary` 单独保存 RSS/搜索摘要，不能替代正文；
- body hash 未变化时不制造新 revision；变化时插入新 revision 并把 item 的 `current_revision_id` 前移；
- revision 不原地改写，因此可以解释某个历史答案当时看见了哪一版原文。

### 2.4 `content_chunk`：RAG 的物理证据行

```yaml
id: <物理证据 UUID>
content_revision_id: <正文版本>
chunk_set_id: <同一次切分批次>
is_active: true
ordinal: 0
heading_path: ["Highlights", "Inference"]
body_text: "这个段落的原始正文……"
token_count: 503
char_start: 0
char_end: 2015
search_vector: <PostgreSQL tsvector>
embedding: <bge-m3 1024 维 pgvector>
```

同一 revision 重切时，事务内先把旧 chunk set 标为 `is_active=false`，再插入一组新 UUID；旧行不删除、不覆写。在线检索只看 active set，历史 `rag_citation` 仍能访问旧证据。这是“索引可升级”和“历史引用不可变”同时成立的关键。

## 3. 不同信源的入库路径并不一样

| 信源类型 | 发现阶段拿到什么 | 最终正文从哪里来 | revision 的正文形态 | 切分特点与失败边界 |
|---|---|---|---|---|
| RSS / Atom 新闻 | guid、标题、链接、时间、feed summary | 再请求文章 URL，Trafilatura 抽正文 | Markdown + 纯文本 | feed summary 只进 `discovery_summary`；回源失败或正文门禁不通过，不能拿摘要冒充全文 |
| 静态列表 → 文章 | 列表页中的候选链接与少量标题 | 候选详情页 | Markdown + 纯文本 | 列表页重复链接先规范化；正文仍走同一全文门禁 |
| GitHub Releases API | tag、release URL、发布时间、完整 release body | GitHub API 返回的 `body` | 原始 Markdown 同时写正文 | heading、列表、代码围栏保留较好；上游 `<img>`/HTML 标签可能作为文本存在，网页预览会清理，但 RAG 仍是文本索引 |
| GitHub 仓库活动 | 仓库 API 的事件/README 类完整文本 | GitHub API | Markdown | 外部 ID 与更新时间用于幂等；短事件可能因正文不足 200 字跳过 LLM 结构化，但仍可保留原始内容 |
| Docs Changelog | 文档页/更新页 | Trafilatura XML 中的 heading 与段落 | 重新组织的 Markdown section | 显式 heading 对结构切块最友好；页面大改产生新 revision |
| arXiv | RSS 中的论文 ID、标题、摘要、时间 | 优先 `arxiv.org/html/{id}`，不可用时下载 PDF | HTML 抽取文本，或 `[Page N]` 分隔的 PDF 文本 | RSS abstract 不是论文全文；PDF 最多受页数与总字符上限保护，扫描版/图片文字没有 OCR 时会拒绝或缺失 |
| Hugging Face / 公开 API | model id、更新时间、模型卡/abstract | API 返回的完整 model card 或公开记录 | Markdown/文本 | 模型卡可能很长，超大单块会被硬切；只有 abstract 的 profile 只能按 metadata 能力使用，不能伪装成全文文章 |
| metadata-only | 标题、URL、时间、少量元数据 | 没有合规全文 | 不创建可用全文 revision，或明确低能力状态 | 可用于发现/来源健康，不应进入“全文已覆盖”统计与 RAG 证据库 |

### 3.1 具体例子：RSS 新闻

以 NVIDIA Blog 的 RSS 条目为例：RSS 给系统的是标题、链接、发布日期和摘要。系统先把这些作为候选，然后请求文章详情页；Trafilatura 以 `include_tables=true` 分别抽取纯文本和 Markdown。2026-08-15 本地抽样中，一篇 NVIDIA Blog 正文约 5,288 字符，保存的是回源正文，不是 feed 摘要。

如果详情页返回登录墙、导航页、极短正文或链接密度异常，全文门禁将它判为 REJECTED/metadata-only。此时宁可暂时不能回答，也不把三行 RSS 摘要切成“全文证据”。

### 3.2 具体例子：GitHub Release

`llama.cpp` release API 的 `body` 本身就是完整发布说明，所以不再抓网页正文。2026-08-15 本地样例约 3,836–5,083 字符，其中一个 revision 被切成三块：

```text
chunk 0: 约 503 tokens，char 0–2015
chunk 1: 约 886 tokens，char 2016–3838
chunk 2: 约 531 tokens，char 3839–4141
```

第二块超过 700 的软目标，是因为一个完整结构块在 1,200 token 硬上限内时优先保持语义完整；超过 1,200 才强制拆开，避免 embedding 供应商只看见前半段。

### 3.3 具体例子：arXiv HTML / PDF

arXiv RSS 的 abstract 只做发现。系统优先请求实验性 HTML；HTML 缺失或结构不合格时请求 PDF，使用 PyMuPDF 按阅读顺序抽纯文本，并插入 `[Page 1]`、`[Page 2]` 分隔符。

当前 chunk 表的 `page_no` 没有被处理管线赋值，页码仍只存在于正文标记里；因此引用能回到论文 URL 和证据文本，但尚不能稳定跳到 PDF 的具体页坐标。这是已知边界，不应宣称具备版面级 PDF RAG。

## 4. 当前切块算法到底怎样工作

实现位置：`apps/ai-service/src/ahr/processing/chunking.py`。

| 常量 | 当前值 | 目的 |
|---|---:|---|
| `TARGET_TOKENS` | 400 | 常规段落达到该大小后优先出块 |
| `MIN_TOKENS` | 120 | 过短块尝试与同节/同父级兄弟块合并 |
| `MAX_TOKENS` | 700 | 常规聚合软上限；单个结构块可暂时超过 |
| `OVERLAP_TOKENS` | 60 | 同一 heading 内携带前块句尾上下文 |
| `HARD_MAX_TOKENS` | 1200 | 任何单块的强制上限，保证 embedding 看见整块 |

估算器按中文、日文、韩文约 1.5 字符/token，其余文本约 4 字符/token，解决只按英文比例导致中文块严重超长的问题。

```text
Markdown / text
  → 识别 heading、空行、列表/段落、代码围栏
  → 建立 heading_path
  → 同一 heading 内累积到约 400 tokens
  → 预计超过 700 时先出块
  → heading 变化立即出块并取消跨节 overlap
  → 单一结构块 >1200：优先按行，再按空白/中英文标点硬切
  → <120 的碎片，只在同 heading 或同父级兄弟 section 内合并
  → 生成 ordinal、字符偏移、token_count
```

三个重要约束：

1. 不把两个顶级章节混入同一块，否则一条引用无法说明自己支持哪一节；
2. 不在不同 heading 间携带 overlap，否则前一节的句子会污染下一节；
3. 表格、代码、长发布日志尽量按行保留，但“可被完整 embedding”高于“永不拆结构”。

## 5. 实际语料与理想目标为什么会有差距

2026-08-15 本地 active chunk 抽样（开发库，不等于生产实时值）：

| profile | items | chunks | 平均估算 tokens | 观察 |
|---|---:|---:|---:|---|
| arXiv | 292 | 1,253 | 826.7 | HTML/PDF 经常把长段落压成少数物理行，heading 恢复弱，较多块靠 1,200 硬上限切开 |
| GitHub Releases | 751 | 3,460 | 362.1 | Markdown heading 保存最好，3,038 个块带 heading path |
| RSS / Article | 692 | 1,359 | 824.5 | 部分网页正文段落很长，平均值高于 400 目标 |
| Public API / model card | 97 | 1,091 | 308.8 | 列表与 Markdown 较多，块更细 |
| Docs Changelog | 11 | 23 | 731.7 | 样本少，section 保持优先 |

这说明“真正分块成功”应分两层回答：

- **索引完整性已成功**：所有 active chunk 有稳定 revision、字符偏移、1024 维 bge-m3 embedding，硬上限修掉了 embedding 截断形成的检索盲区；
- **结构质量仍不完全均匀**：扁平 HTML、PDF 与部分 RSS 正文缺少可恢复 heading，实际块可能靠长段落/行边界切开。后续若引入 DOM section、PDF layout block 或专用解析器，应先用固定黄金集证明收益再替换。

## 6. 图片、表格、代码与 PDF 的真实边界

### 图片

当前没有图片下载、OCR、caption 模型、多模态 embedding 或图文对齐表。Trafilatura 没有开启图片抽取；图片本身不会进入 `content_chunk`。如果正文显式写了图注/alt，抽取器可能保留其可见文本，但不能保证；GitHub release body 中的 Markdown/HTML 图片标签可能作为原始文本残留，这不等于理解了图片。

因此：包含文字截图、图表结论或公式图片的文章，RAG 只能使用周围可抽取文字。答案不能根据图片做事实断言。要做多模态，至少需要独立 media asset、OCR/caption provenance、图文 chunk 关系、模型版本和新的黄金集；不能只把图片 URL 拼进 prompt。

### 表格和代码

网页抽取启用表格保留，Markdown/代码围栏尽可能按整体结构切分。极大表格或单行压缩代码超过 1,200 tokens 时仍会切开；这是“局部结构完整”与“向量模型可见范围”之间的显式取舍。

### PDF

只有 arXiv PDF 文本兜底：PyMuPDF 读取文本层，限制页数和总字符；没有 OCR、公式结构恢复、表格识别、图片理解与 bbox 级引用。扫描件没有文本层时会被识别为无可抽取正文，而不是生成看似完整的空洞 chunk。

## 7. 失败、重试与重新切块

- 网络请求：有 timeout、有界重试、每 host 限速、ETag/Last-Modified 与错误分类；
- 正文质量不合格：保留抓取审计，不写可检索假全文；
- LLM 结构化失败：原始 revision/chunk 仍在，`enrichment_state` 记录失败；公共中文列表不再展示半成品；
- 重复内容：规范化 URL、内容 hash 和近似重复分层处理；
- chunk 算法升级：显式 `rechunk` 生成新 active chunk set，再重新 embedding；历史引用不变；
- embedding 未完成：该 chunk 不进入向量召回；语料 fingerprint 只统计可检索 chunk，避免用“已入库但不可检索”的内容错误失效缓存。

## 8. 为什么没有直接使用 LangChain 文档切分器

当前切块需求和数据库不变量很具体：CJK token 估算、heading path、字符偏移、物理引用不可变、同 revision 多 chunk set、历史 citation FK。直接套通用 splitter 仍需在外层补齐这些语义，而且会把关键行为藏在框架默认值里。

保留自研小型切块器的收益是规则可测试、变更可用黄金集做 A/B、引用坐标可解释。只有当通用框架对特定格式（例如 PDF layout 或 HTML DOM）带来可量化收益时，才应把它作为 adapter，而不是重写整个 RAG 编排。

## 9. 面试深挖问答

**问：RAG 切的是 AI 摘要还是原文？**

答：切的是 `content_revision.body_markdown/body_text` 的回源正文。RSS 摘要单独放 `discovery_summary`，中文标题和摘要是 LLM 展示投影，不能成为最终 evidence。引用在服务端绑定物理 `content_chunk` 和原文 URL。

**问：为什么 relevant 标注在 item，不标 chunk？**

答：chunk 会随切分算法重建，item ID 跨重切稳定。检索 Recall 先评文档是否进入候选，段落是否真正支持结论再由 generation/citation 指标和人工审计检查。

**问：400 token 为什么数据库里平均还有 800？**

答：400 是目标，不是硬切线。算法优先不破坏单一 heading/表格/代码结构；真正不可超过的是 1,200。扁平 HTML/PDF 会形成长物理段落，所以需要硬上限兜底。这个差距被实测并保留为结构解析的改进空间，而不是声称所有块都是 400。

**问：图片怎么办？**

答：当前是 text-only RAG，图片不会被视觉理解。图注如果成为可抽取文本可以参与，否则拒绝据图推断。多模态需要新的数据实体、provenance、模型和评测，不应暗中混入现有文本证据链。

**问：重切后旧答案的引用会不会失效？**

答：不会覆写旧物理行。新 chunk set 激活、旧 set 退役；在线只检索 active，历史 citation 仍指旧 chunk，因此旧答案仍能复核当时证据。

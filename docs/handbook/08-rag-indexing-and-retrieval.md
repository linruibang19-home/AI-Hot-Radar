# 08｜RAG：索引、查询理解与混合检索

## 1. RAG 的目标

系统不追求“任何问题都聊”，只回答站内已采集 AI 情报。一个合格回答需要同时满足：找到正确
内容、时间范围正确、不同来源不过度重复、答案只说证据支持的内容、引用能回到原文。

## 2. 入库与索引

正文 revision 按标题/段落结构切成 `content_chunk`。每个 chunk 保存原文、heading path、ordinal、
token count、FTS `search_vector`、1024 维 embedding、模型和处理版本。过短相邻段合并，超长段
切分，不跨顶层章节。模型供应商返回的维度、数量和顺序必须验证后才落库。

逻辑 evidence passage 就是可引用的 chunk；没有独立 `evidence_passage` 或 `embedding_record`
表。自适应 parent context 在查询时由相邻 chunk 派生，引用仍指 child。

## 3. 问题预处理

### 多轮改写

只把必要的上文实体带入独立问题，例如“它最近有什么更新”改为“MiniMax 最近有什么更新”。
改写器看用户问题，不把上一轮答案当事实，否则幻觉会被洗入新查询。失败时退回原问题。

### 查询类型

系统区分近期动态、时间线、比较、事实核查、原理解释和不可答等类型，因为它们需要不同的
时间窗口、来源偏好和候选深度。

### 时间解析

“最近 7 天”按请求时区转换为绝对起止时间；最终计划和页面都显示这个范围。时间是 SQL
过滤和后续重排信号，不是只写进 prompt。

### 实体与别名

受控实体/alias 解决中英文、产品简称和模型版本。最长匹配优先，模型家族可归一，但不能把
不同版本的事件直接合并。

## 4. 三个主召回通道

| 通道 | 技术 | 擅长 | 弱点 |
|---|---|---|---|
| Dense | SiliconFlow embedding + pgvector | 语义改写、跨语言 | 精确版本/编号可能弱 |
| Sparse | PostgreSQL tsvector/GIN + CJK bigram | 型号、术语、字面命中 | 同义改写弱 |
| Temporal/entity | SQL 结构化过滤与时效候选 | 最近、时间线、指定主体 | 依赖元数据质量 |

PostgreSQL sparse 是有意选择，不是假装 BM25/Elasticsearch 已存在。当前语料规模下，同库过滤、
事务一致性和运维简化更有价值。

## 5. 候选融合

不同通道分数不可直接相加。RRF 用名次而非原始分数融合，降低不同量纲影响。早期 B2 试验把
稀疏和稠密简单轮转，局部问题变好但总体 MRR 下降，证明“多一个通道”不等于系统提升。

融合后追加有界元数据调整：

- 问题主体是候选主语时小幅提升；
- 近重复/转载降权而非全部删除；
- 来源集中度上限，避免一个站占满；
- query type 与 source type 适配；
- 时间敏感问题增加新鲜度，但相关性仍占主导。

## 6. 交叉编码器重排

Reranker 只处理有限 shortlist，输出 question/passage 相关性。它比 embedding 精细，但调用更慢、
成本更高，因此不能全库使用。重排后再做 story folding、source cap 和证据集选择。

如果 reranker 超时，系统可用融合排序降级；但 trace 必须标明 degraded，评测不能把两者混为一轮。

## 7. 自适应 Parent Context

检索和引用需要精确 child，生成又需要上下文。系统按同 revision 的 ordinal 向前后展开小窗口，
在 token 预算内形成 parent block。这样不新增同步表，也不会把一整篇文档作为含糊引用。

## 8. 缓存

答案 key 包含规范问题、prompt/processor 版本和语料指纹。时效问题绑定严格语料新鲜度；解释类
问题可使用更粗粒度指纹。拒答、未提交答案和无法绑定引用的结果不缓存。Redis 故障时回源执行，
不能让缓存成为事实源。

## 9. 检索 trace

每次查询应记录：计划、绝对时间范围、通道候选数、融合/重排分数、折叠和降权原因、最终证据、
各阶段耗时、provider/model/version。Trace 用于评测和排障，公共页面只展示安全摘要。

## 10. 关键代码

- `rag/planner.py`、`llm_planner.py`、`temporal.py`、`conversation.py`
- `rag/retrieval.py`、`fusion.py`、`rerank.py`、`dimensions.py`
- `rag/folding.py`、`parent.py`、`context.py`
- `rag/embeddings.py`、`cache.py`、`trace.py`
- ADR-0015/0016/0017/0018

## 11. 当前边界

- 不支持任意 embedding 模型热切换；
- 不使用 Elasticsearch/OpenSearch；
- 不使用 GraphRAG/RAPTOR；
- 评测集以 AI 行业时效问题为主，不代表通用知识问答；
- 语料质量仍受公开来源可访问性影响。


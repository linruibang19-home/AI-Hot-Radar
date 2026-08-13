# RAG 语料、原文切块与向量覆盖审计（2026-08-13）

本文件记录一次生产只读审计和由它触发的缺陷修复。数字是该时点快照，不是 README 的永久指标。
审计没有导出正文、密钥、邮箱或管理凭据。

## 要回答的问题

1. RAG 是否真的对 canonical 正文切块，而不是对 AI 摘要切块？
2. 当前 revision 是否都有 chunk，chunk 是否都有向量？
3. 分块参数与字符定位是否满足实现契约？
4. 还有哪些不能据此证明？

## 数据路径证据

```text
canonical 回源 / API 原文
→ content_revision.body_text
→ chunk_current_revisions()
→ chunk_revision(revision_id, body_text)
→ content_chunk.body_text + heading_path + char_start/end
→ build_embedding_text(上下文前缀 + 原文 passage)
→ BAAI/bge-m3
→ content_chunk.embedding
```

`summary_zh` 由 LLM enrichment 单独写入 `content_item`，不在上述切块调用路径。上下文前缀只进入
Embedding/Reranker 输入；引用绑定时仍从 `content_chunk.body_text` 和 canonical URL 取证。

## 修复前生产快照

| 检查 | 结果 | 解释 |
|---|---:|---|
| 当前非重复内容 | 2,111 | 只统计 `duplicate_of_id IS NULL` |
| 当前非空正文 | 2,098 | 13 条空正文不进入 RAG |
| 已切块的当前正文 | 2,095 | 3 条刚进入流水线：两篇网页正文和一个 18 字符 API body |
| 全历史 chunk | 8,915 | 含仍保留审计的旧 revision |
| 当前 revision chunk | 7,912 | 在线检索只 join current revision |
| 当前 chunk 有向量 | 7,912 / 7,912 | 模型全部为 `BAAI/bge-m3` |
| chunk 等于 `summary_zh` | 0 | 反证“摘要直接当 chunk” |
| 有效字符定位 | 7,912 / 7,912 | `0 <= start < end <= revision length` |
| 当前 chunk <= 1,200 token | 7,898 / 7,912 | 暴露 14 个超长单行历史块 |
| 全文门 ACCEPTED | 2,704 | 另有 185 metadata-only、19 rejected |

正文 extraction method 主要为 `trafilatura` 1,352 个 revision、`api_body` 851、`arxiv_html` 64、
`arxiv_pdf_pymupdf` 3。抽查长文可见一篇 89,338 字符 changelog 形成 93 个已向量化 passage；这不是
一个摘要长度的数据形态。

`exact_substring` 不能要求 100%：普通 chunk 会带 60-token overlap，跨块拼接后不一定是 revision 中
一个连续子串；可验证性使用原文字符定位、heading 和最小 passage，而不是用这个指标替代契约。

## 找到并修复的缺陷

14 个当前块超过 1,200-token 硬上限，最大 4,904。根因不是摘要，而是网页抽取把长正文压成一个
没有换行的物理行；旧 `_split_oversized()` 只按行切，所以无法继续拆这一个长行。

修复：

- 超长单行按估算 token 二分预算，优先附近空白/标点，保留所有有意义字符与精确 offset；
- 新增单行超限、不丢正文、连续 offset 的回归测试；
- CLI 增加 `rechunk --oversized-only`，只重建当前 revision 中超限的块；
- 重建会删除旧 chunk/embedding，新块由现有 `embed` 幂等补向量，不全库重算。

部署验收应满足：当前超限块为 0、当前非空正文全部切块、当前 chunk 全部有相同 embedding model。

## 能证明与不能证明

能证明：实现和生产数据都走原文 revision → passage → vector 路径；当前向量覆盖完整；引用正文没有
被合成上下文或摘要替换；异常块能由数据审计发现并定向修复。

不能证明：自动向量覆盖不等于每个答案都正确；黄金集 90 题仍有样本规模和领域覆盖边界；主题地图
1,995 条候选没有完成双人盲审，不能声称其人工 precision/recall 已达标；私有知识库的 ACL/租户隔离
不在当前公开资讯产品范围。

## 复核命令类别

- PostgreSQL 只读聚合：current revision、nonempty body、chunk、embedding、model、offset、超限数；
- `pytest test_chunk_quality.py test_rechunk_invariant.py`；
- 部署后 `python -m ahr.cli rechunk --oversized-only`；
- 循环执行 `python -m ahr.cli embed --limit 500 --batch-size 64` 至 remaining 为 0；
- 重新跑 RAG 定向测试/发布门，确认 chunk identity 变化没有破坏引用绑定。

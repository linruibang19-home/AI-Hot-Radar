"""Turn mined candidates into a sheet a human can annotate.

`candidates.mine` says *which* questions are worth the time. This says what an
annotator has to look at to decide, and emits it in the golden set's own YAML
so that filling the blanks produces the file rather than a thing that needs
converting.

**The document list comes from `rag_trace`, not `rag_citation`.** Citations are
what the pipeline chose; showing only those lets an annotator confirm the
system and never contradict it, which is the one judgement worth paying for. A
relevant document the ranker dropped at #35 is exactly the case the golden set
should record, and it is only visible in the trace.

Grades follow the existing files: 2 for strongly relevant, 1 for weak, and the
line deleted when the document does not belong. Every grade starts as `?` so an
unfinished sheet fails validation instead of silently annotating everything as
irrelevant.
"""

from __future__ import annotations

from typing import Any

#: Trace rows carry the whole rerank window. More than this and the sheet stops
#: being something a person will actually read to the bottom.
MAX_DOCUMENTS = 18

#: Enough of the passage to judge relevance without opening the article.
EXCERPT_CHARS = 150

OUTCOME_LABELS = {
    "cited": "被引用",
    "evidence_uncited": "进证据未引用",
    "dropped_document_cap": "同篇超额",
    "dropped_source_cap": "同信源超额",
    "dropped_story_fold": "同事件折叠",
    "dropped_budget": "预算已满",
    "ranked_out": "未进证据",
}

_TRACE = """
    SELECT t.content_item_id::text,
           COALESCE(ci.zh_title, ci.title),
           s.name,
           COALESCE(ci.published_at, ci.observed_at),
           t.outcome,
           t.fused_rank,
           t.rerank_rank,
           left(regexp_replace(ch.body_text, '\\s+', ' ', 'g'), %(chars)s)
      FROM rag_trace t
      JOIN content_chunk ch ON ch.id = t.content_chunk_id
      LEFT JOIN content_revision cr ON cr.id = ch.content_revision_id
      LEFT JOIN content_item ci ON ci.id = cr.content_item_id
      LEFT JOIN source s ON s.id = ci.source_id
     WHERE t.rag_query_id = %(query_id)s
       AND t.content_item_id IS NOT NULL
     ORDER BY COALESCE(t.rerank_rank, 9999), COALESCE(t.fused_rank, 9999)
     LIMIT %(limit)s
"""


def _escape(text: str) -> str:
    """YAML double-quoted scalar. Questions contain colons often enough."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


#: Everything the answer cited, for questions asked before `rag_trace` began
#: writing on 2026-08-06. Strictly worse — it shows what the pipeline chose and
#: not what it looked at — so the sheet says which one it used.
_CITED = """
    SELECT ci.id::text,
           COALESCE(ci.zh_title, ci.title),
           s.name,
           COALESCE(ci.published_at, ci.observed_at),
           'cited',
           NULL::int,
           c.citation_no,
           left(regexp_replace(ch.body_text, '\\s+', ' ', 'g'), %(chars)s)
      FROM rag_citation c
      JOIN content_chunk ch ON ch.id = c.content_chunk_id
      LEFT JOIN content_revision cr ON cr.id = ch.content_revision_id
      LEFT JOIN content_item ci ON ci.id = cr.content_item_id
      LEFT JOIN source s ON s.id = ci.source_id
     WHERE c.rag_query_id = %(query_id)s
     ORDER BY c.citation_no
     LIMIT %(limit)s
"""


def _documents(connection: Any, query_id: str) -> tuple[list[dict[str, Any]], bool]:
    """Documents to judge, and whether they came from the full funnel."""
    params = {"query_id": query_id, "limit": MAX_DOCUMENTS, "chars": EXCERPT_CHARS}
    with connection.cursor() as cursor:
        cursor.execute(_TRACE, params)
        rows = cursor.fetchall()

    traced = bool(rows)
    if not traced:
        with connection.cursor() as cursor:
            cursor.execute(_CITED, params)
            rows = cursor.fetchall()

    seen: set[str] = set()
    documents: list[dict[str, Any]] = []
    for item_id, title, source, published, outcome, fused, rerank, excerpt in rows:
        # One row per *document*: the trace is per passage, and a document with
        # three passages in the window is still one relevance judgement.
        if item_id in seen:
            continue
        seen.add(item_id)
        documents.append(
            {
                "id": item_id,
                "title": (title or "（无标题）").strip(),
                "source": (source or "?").strip(),
                "published": published.date().isoformat() if published else "?",
                "outcome": OUTCOME_LABELS.get(outcome, outcome),
                "fused_rank": fused,
                "rerank_rank": rerank,
                "excerpt": " ".join((excerpt or "").split()),
            }
        )
    return documents, traced


def render(connection: Any, candidates: list[dict[str, Any]], *, category: str) -> str:
    """Emit the annotation sheet as golden-set YAML with `?` grades."""
    lines = [
        "# 标注工作表 —— 从真实提问挖出来的候选，尚未标注。",
        "#",
        "# 每题按下面三步填：",
        "#   1. answerable: 语料里是否真的答得出来。答不出就改成 false，",
        "#      并补 presupposition（这题预设了什么）和 must_not_claim（不许出现的词）。",
        "#   2. 每个候选文档把 grade: ? 改成 2（强相关）或 1（弱相关）；",
        "#      不相关的整行删掉。全删光说明这题不可答。",
        "#   3. notes 写这题考的是什么——将来的人靠它判断题目还成不成立。",
        "#",
        "# 文档列表来自 rag_trace，包含检索看过但丢弃的。漏标的相关文档就藏在",
        "# 「未进证据」那几行里；只看被引用的，就只能给系统点头。",
        "#",
        "# 校验：ahr golden-validate <本文件>。留着 ? 会直接失败。",
        "",
        f"category: {category}",
        "questions:",
    ]

    for candidate in candidates:
        documents, traced = _documents(connection, candidate["query_id"])
        lines.append("")
        lines.append(
            f"  # 挖出的理由: {candidate['band']}"
            + (
                f" · 最低支持度 {candidate['worst_support']}"
                if candidate.get("worst_support") is not None
                else ""
            )
        )
        lines.append(f"  - id: TODO-{candidate['query_id'][:8]}")
        lines.append(f'    question: "{_escape(candidate["question"])}"')
        lines.append(f"    asked_at: {candidate['asked_at']}")
        lines.append("    answerable: true")
        lines.append("    relevant_items:")
        if not traced and documents:
            # Said out loud, because it changes what the annotator can conclude:
            # they can confirm or reject what was cited, but cannot catch a
            # relevant document the ranker dropped — there is no record of it.
            lines.append(
                "      # 注意：这题早于 rag_trace，下面只有被引用的文档，看不到检索丢弃了什么"
            )
        if not documents:
            lines.append("      # 检索没有留下任何候选——这题多半应当 answerable: false")
        for document in documents:
            rank = document["rerank_rank"] or document["fused_rank"] or "—"
            lines.append(
                f"      # [{document['outcome']}] #{rank} {document['source']}"
                f" · {document['published']} · {document['title'][:52]}"
            )
            if document["excerpt"]:
                lines.append(f"      #   {document['excerpt'][:110]}")
            lines.append(f"      - {{id: {document['id']}, grade: ?}}")
        lines.append('    notes: "TODO 这题考什么"')

    lines.append("")
    return "\n".join(lines)


def validate(text: str) -> list[str]:
    """Problems that would make a filled sheet unusable as a golden file.

    Checked as text before YAML parsing, because `grade: ?` is not valid YAML
    and the unfinished state is the one this most needs to catch. Returns an
    empty list when the sheet is ready to move into `data/golden/`.
    """
    problems: list[str] = []

    unfilled = text.count("grade: ?")
    if unfilled:
        problems.append(f"{unfilled} 个文档还没打分（grade: ?）")

    todo_ids = text.count("id: TODO-")
    if todo_ids:
        problems.append(f"{todo_ids} 道题还是占位 id（id: TODO-…），需要改成 RAG-GOLD-NNN")

    todo_notes = text.count('notes: "TODO')
    if todo_notes:
        problems.append(f"{todo_notes} 道题的 notes 还没写")

    # An unanswerable question needs the two fields the abstention scorer reads;
    # without them it grades as answerable-with-no-evidence, which is a
    # different and much weaker test.
    import re

    for block in re.split(r"\n  - id: ", text)[1:]:
        if "answerable: false" not in block:
            continue
        identifier = block.split("\n", 1)[0].strip()
        if "presupposition:" not in block:
            problems.append(f"{identifier}: answerable false 但缺 presupposition")
        if "must_not_claim:" not in block:
            problems.append(f"{identifier}: answerable false 但缺 must_not_claim")

    return problems

"""Follow-up questions, by rewriting them into standalone ones (Phase C).

Asked 「它的参数量呢？」 the system answered 「没有单一模型被明确指定为"它"」 — correctly,
because nothing carried the previous turn. `rag_query.conversation_id` has existed
since V001 and was written by nothing; every question was its own session.

**Rewriting, not history-stuffing.** The obvious implementation is to prepend the
transcript to the generation prompt, and it is the wrong one here: retrieval
happens *before* generation, so a prompt-level fix leaves the retriever searching
for 「它的参数量呢」 — a query with no content words, which the sparse channel drops
entirely and the dense channel matches to nothing in particular. The answer would
be assembled from whatever came back. This is the standard solution for the same
reason Perplexity and ChatGPT Search use it: the follow-up becomes a standalone
query first, and everything downstream is unchanged.

**Old answers are not evidence, and the rewriter is where that could break.**
`AHR-RAG-400` §11 is explicit: facts are re-retrieved every turn and a previous
answer must never be treated as a new fact. So the rewriter is given the previous
*questions* and the *titles* of what was cited — document titles are corpus
facts with a source behind them — and never the model's own prose. An antecedent
that exists only inside a generated sentence is one this deliberately cannot
resolve; inventing it back would be laundering an unverified claim into the next
query.

**Failure is silent and cheap.** No prior turns, a provider wobble, an empty or
suspiciously long rewrite — all fall back to the question as typed. A follow-up
answered without context is a worse answer; a follow-up that errors is no answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ahr.processing.llm import LlmClient, LlmUnavailableError

logger = logging.getLogger(__name__)

REWRITE_PROMPT_VERSION = "rag-rewrite-v1"

# §11: the recent transcript, not the whole session. Enough to resolve a
# pronoun, short enough that the rewrite stays cheap and cannot drift into
# summarising a conversation nobody asked it to summarise.
MAX_TURNS = 6

# A rewrite far longer than the question is not a rewrite. Seen in prompt
# testing: the model occasionally answers the question instead of restating it,
# and a paragraph reaching the retriever would search for the model's guess.
MAX_REWRITE_RATIO = 6
MAX_REWRITE_CHARS = 300

SYSTEM_PROMPT = """你把追问改写成一个可以独立检索的问题。

规则：
1. 把代词（它、他们、这个、那个）和省略的主语替换成前文提到的具体名字。
2. 只补充前文里出现过的名字，不要引入前文没有的任何信息。
3. 如果这个问题本身已经完整、不依赖前文，原样输出。
4. 保留原问题的时间表达；如果新问题带了新的时间词，以新的为准。
5. 只输出改写后的问题本身，不要解释，不要加引号。"""


@dataclass(frozen=True)
class Turn:
    """One earlier exchange, reduced to what may safely inform a rewrite."""

    question: str
    cited_titles: tuple[str, ...]


def load_turns(connection: Any, conversation_id: str, *, limit: int = MAX_TURNS) -> list[Turn]:
    """Recent turns of this conversation, oldest first.

    Answer text is deliberately not selected. The titles come from
    `content_item`, so everything handed to the rewriter is something the corpus
    says rather than something the model said.

    The *rewritten* form of each earlier question is preferred where one exists
    (`retrieval_plan.question`), because that is the one carrying the resolved
    names. A chain of follow-ups — 「它呢」 then 「那它的价格呢」 — is only
    resolvable if the middle turn contributes the name rather than the pronoun
    it was typed as.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(q.retrieval_plan->>'question', q.question),
                   COALESCE(
                       array_agg(DISTINCT COALESCE(ci.zh_title, ci.title))
                           FILTER (WHERE ci.id IS NOT NULL),
                       '{}'
                   )
              FROM rag_query q
              LEFT JOIN rag_citation c ON c.rag_query_id = q.id
              LEFT JOIN content_chunk ch ON ch.id = c.content_chunk_id
              LEFT JOIN content_revision cr ON cr.id = ch.content_revision_id
              LEFT JOIN content_item ci ON ci.id = cr.content_item_id
             WHERE q.conversation_id = %s::uuid
             GROUP BY q.id, q.completed_at
             ORDER BY q.completed_at DESC NULLS LAST
             LIMIT %s
            """,
            (conversation_id, limit),
        )
        rows = cursor.fetchall()

    return [
        Turn(question=str(row[0]), cited_titles=tuple(str(t) for t in (row[1] or [])[:3]))
        for row in reversed(rows)
    ]


def _transcript(turns: list[Turn]) -> str:
    lines: list[str] = []
    for index, turn in enumerate(turns, start=1):
        lines.append(f"第 {index} 轮提问：{turn.question}")
        if turn.cited_titles:
            lines.append(f"  当时引用的文档标题：{'；'.join(turn.cited_titles)}")
    return "\n".join(lines)


def _acceptable(question: str, rewritten: str) -> bool:
    """Whether the rewrite is a restatement rather than something else.

    A rewrite is supposed to be roughly the question with its pronouns filled
    in. Anything much longer is the model having answered instead, and letting
    that reach the retriever would search for its guess.
    """
    if not rewritten:
        return False
    if len(rewritten) > MAX_REWRITE_CHARS:
        return False
    return len(rewritten) <= max(MAX_REWRITE_CHARS, len(question) * MAX_REWRITE_RATIO)


async def rewrite(
    llm: LlmClient,
    question: str,
    turns: list[Turn],
) -> tuple[str, bool]:
    """Return a standalone question, and whether it was actually rewritten.

    The flag matters to the page: a reader whose follow-up was understood as
    something else needs to see what it became, the same way the resolved time
    window is shown rather than merely applied.
    """
    if not turns:
        return question, False

    try:
        raw, _usage = await llm.summarize(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=f"{_transcript(turns)}\n\n本轮提问：{question}\n\n改写后的问题：",
        )
    except LlmUnavailableError as exc:
        logger.warning("rewrite unavailable, using the question as typed: %s", exc)
        return question, False

    rewritten = raw.strip().strip('"').strip("「」")
    if not _acceptable(question, rewritten):
        logger.warning("rewrite rejected (%d chars), using the question as typed", len(rewritten))
        return question, False

    return rewritten, rewritten != question

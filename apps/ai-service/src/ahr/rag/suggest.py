"""Follow-up suggestions, grounded in what was actually retrieved.

Multi-turn works and nothing on the page invites a second turn: the reader has to
think of one and type it. Related questions are the feature that makes a
conversational search product feel conversational, and this one has the material
to build them honestly — the entities the planner resolved and the documents that
were actually cited.

**Grounded, not imagined.** A suggestion the corpus cannot answer is worse than
none: the reader clicks it, gets a refusal, and learns the suggestions are
decoration. So the model is given the titles and entities of the passages this
answer cited, and told to propose questions those documents could answer. It is
still a suggestion rather than a promise — the corpus moves — but it is drawn
from what was there a moment ago rather than from the model's general knowledge.

**Off the critical path.** Fetched after the answer has rendered, never before
it. The latency run put p50 at ~10s with 99% of it in three external round trips;
adding a fourth to a stage the reader is already waiting through would make the
answer slower to buy something they have not asked for yet. A failure here
produces no chips and no error — the page is exactly what it was.

**Cached by query id.** The suggestions for an answer cannot change while the
answer does not, so re-reading a permalink costs nothing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ahr.processing.llm import LlmClient, LlmUnavailableError

logger = logging.getLogger(__name__)

SUGGEST_PROMPT_VERSION = "rag-suggest-v1"

MAX_SUGGESTIONS = 3

# Long enough to be specific, short enough to render as a chip. A suggestion
# that wraps to three lines is a paragraph pretending to be a button.
MAX_SUGGESTION_CHARS = 40

SYSTEM_PROMPT = """你根据一次问答，提出读者接下来最可能想问的问题。

规则：
1. 只提 3 个问题，每个不超过 25 个字。
2. 必须能用给定的这些文档回答——不要提这些文档里没有的内容。
3. 不要重复刚才已经问过的问题。
4. 每个问题都要能独立看懂，不要用「它」「这个」等代词。
5. 只输出 JSON 数组，例如：["问题一", "问题二", "问题三"]"""


def _context(connection: Any, query_id: str) -> tuple[str, list[str], list[str]]:
    """The question, the cited titles, and the entities behind them."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT q.question,
                   COALESCE(
                       array_agg(DISTINCT COALESCE(ci.zh_title, ci.title))
                           FILTER (WHERE ci.id IS NOT NULL),
                       '{}'
                   ),
                   COALESCE(
                       array_agg(DISTINCT e.name) FILTER (WHERE e.name IS NOT NULL),
                       '{}'
                   )
              FROM rag_query q
              LEFT JOIN rag_citation c ON c.rag_query_id = q.id
              LEFT JOIN content_chunk ch ON ch.id = c.content_chunk_id
              LEFT JOIN content_revision cr ON cr.id = ch.content_revision_id
              LEFT JOIN content_item ci ON ci.id = cr.content_item_id
              LEFT JOIN item_entity ie ON ie.content_item_id = ci.id AND ie.role = 'subject'
              LEFT JOIN entity e ON e.id = ie.entity_id
             WHERE q.id = %s::uuid
             GROUP BY q.id
            """,
            (query_id,),
        )
        row = cursor.fetchone()

    if row is None:
        return "", [], []
    return str(row[0] or ""), [str(t) for t in (row[1] or [])], [str(e) for e in (row[2] or [])]


def _parse(raw: str, *, asked: str) -> list[str]:
    """Read the model's array, keeping only what can render as a chip.

    Anything unparseable yields no suggestions rather than a repaired guess:
    the feature is optional, and a malformed reply is not worth salvaging into
    something the corpus may not answer.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    seen: set[str] = set()
    kept: list[str] = []
    for item in parsed:
        candidate = str(item).strip().strip("\"'「」")
        if not candidate or len(candidate) > MAX_SUGGESTION_CHARS:
            continue
        # Suggesting the question just asked wastes a slot and looks broken.
        if candidate == asked.strip() or candidate in seen:
            continue
        seen.add(candidate)
        kept.append(candidate)
    return kept[:MAX_SUGGESTIONS]


async def suggest(connection: Any, llm: LlmClient, query_id: str) -> list[str]:
    """Three follow-ups this answer's own sources could support.

    Returns an empty list for anything that went wrong — a refused answer with
    no citations, a provider outage, an unusable reply. The page renders no
    chips and says nothing about it, which is the correct amount of noise for a
    feature nobody requested.
    """
    asked, titles, entities = _context(connection, query_id)
    if not asked or not titles:
        return []

    context = "刚才的问题：" + asked + "\n\n这次回答引用了以下文档：\n"
    context += "\n".join(f"- {title}" for title in titles[:8])
    if entities:
        context += "\n\n涉及的实体：" + "、".join(entities[:10])

    try:
        raw, _usage = await llm.summarize(system_prompt=SYSTEM_PROMPT, user_prompt=context)
    except LlmUnavailableError as exc:
        logger.warning("suggestions unavailable: %s", exc)
        return []

    return _parse(raw, asked=asked)

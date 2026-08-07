"""How well each cited passage actually supports its claim (T2-4).

`rag_citation.support_score` has existed since V001 and every one of the 560
rows in it was NULL. The column was defined for exactly this number, the
offline generation evaluation computes it for all 90 golden questions, and the
live path — the one a reader looks at — never did.

That gap matters more than it sounds. The evaluation reports a mean support of
0.833 across the golden set; a reader looking at one answer had no way to know
whether *this* citation was one of the good ones or one of the tail. The claim
the product makes is that every fact is checkable, and "checkable" was doing a
lot of work when the only check on offer was reading the passage yourself.

**Same method as the offline run, deliberately.** §10 permits "NLI/cross-encoder
or a controlled LLM"; `eval/generation.py` chose the cross-encoder because it is
already integrated and adds no provider. Using a different method here would
mean the number on the page and the number in the evaluation report were not
comparable, which is worse than having neither.

**Concurrent, because each pair is a separate call.** The rerank API takes one
query against many documents, and support scoring is many queries against one
document each — so it cannot be batched into a single request. Issued together,
the wall clock is one round trip rather than one per citation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ahr.rag.answer import Citation
from ahr.rag.rerank import RerankClient, RerankUnavailableError

logger = logging.getLogger(__name__)

# Shared with the offline evaluation so a citation labelled "supported" on the
# page is the same citation the report counted as supported.
SUPPORT_THRESHOLD = 0.30

# Concurrency for the backfill. The live path scores one answer's citations at
# once — a handful; a backfill has hundreds, and firing them all together would
# be a self-inflicted rate limit.
BACKFILL_BATCH = 8

# The live path scores against the evidence text, which is already capped. A
# backfill reads whole chunk bodies, and a very long one would dominate the
# request without changing the verdict.
MAX_PASSAGE_CHARS = 1200


async def score_citations(
    reranker: RerankClient | None,
    citations: list[Citation],
    passages: dict[str, str],
    *,
    fallback_claim: str,
) -> dict[str, float]:
    """Return `chunk_id -> support score` for every citation that could be scored.

    Takes citations rather than a finished `Answer` because it runs *before* the
    answer object exists — the scores belong on the citations that go into it.

    Missing entries are normal and mean "not scored", never "scored zero": a
    reranker outage would otherwise silently rewrite every citation on the page
    into an unsupported one.
    """
    if reranker is None or not citations:
        return {}

    pairs = [
        (c.chunk_id, c.claim_text or fallback_claim, passages.get(c.chunk_id, ""))
        for c in citations
    ]
    pairs = [(chunk_id, claim, text) for chunk_id, claim, text in pairs if text and claim]
    if not pairs:
        return {}

    async def one(chunk_id: str, claim: str, passage: str) -> tuple[str, float] | None:
        try:
            result = await reranker.rerank(claim, [passage], top_n=1)
        except RerankUnavailableError as exc:
            logger.warning("support scoring unavailable: %s", exc)
            return None
        return (chunk_id, float(result[0][1])) if result else None

    results = await asyncio.gather(
        *(one(chunk_id, claim, text) for chunk_id, claim, text in pairs),
        return_exceptions=True,
    )

    scores: dict[str, float] = {}
    for item in results:
        # A failed pair is dropped, not defaulted. One provider hiccup should
        # cost one score, not mislabel a citation.
        if isinstance(item, BaseException) or item is None:
            continue
        chunk_id, score = item
        scores[chunk_id] = score
    return scores


def summarise(scores: dict[str, float], citations: int) -> dict[str, float | int]:
    """The per-answer figures, in the same shape the evaluation reports."""
    if not scores:
        return {"scored": 0, "citations": citations}

    values = list(scores.values())
    supported = sum(1 for value in values if value >= SUPPORT_THRESHOLD)
    return {
        "scored": len(values),
        "citations": citations,
        "support_mean": round(sum(values) / len(values), 4),
        "support_min": round(min(values), 4),
        "support_supported": round(supported / len(values), 4),
    }


async def backfill(
    connection: Any,
    reranker: RerankClient,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """Score citations written before this module existed.

    Selected by the invariant it maintains — *a citation with a claim and a
    passage has a support score* — rather than by a date or a migration marker.
    That way a citation whose scoring failed at answer time is picked up on the
    next run instead of staying NULL forever because it was not in the original
    backlog.

    Scores are written per batch rather than at the end: a run interrupted
    halfway should leave the work it already paid for.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.rag_query_id::text, c.citation_no, c.content_chunk_id::text,
                   c.claim_text, ch.body_text
              FROM rag_citation c
              JOIN content_chunk ch ON ch.id = c.content_chunk_id
             WHERE c.support_score IS NULL
               AND length(coalesce(c.claim_text, '')) > 0
               AND length(coalesce(ch.body_text, '')) > 0
             ORDER BY c.rag_query_id
             LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    if not rows:
        return {"scored": 0, "remaining": 0}

    async def one(row: tuple[Any, ...]) -> tuple[str, int, float] | None:
        try:
            result = await reranker.rerank(str(row[3]), [str(row[4])[:MAX_PASSAGE_CHARS]], top_n=1)
        except RerankUnavailableError as exc:
            logger.warning("backfill scoring unavailable: %s", exc)
            return None
        return (str(row[0]), int(row[1]), float(result[0][1])) if result else None

    scored = 0
    for start in range(0, len(rows), BACKFILL_BATCH):
        batch = rows[start : start + BACKFILL_BATCH]
        results = await asyncio.gather(*(one(row) for row in batch), return_exceptions=True)
        updates = [r for r in results if isinstance(r, tuple)]
        if not updates:
            continue

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                UPDATE rag_citation SET support_score = %s
                 WHERE rag_query_id = %s::uuid AND citation_no = %s
                """,
                [(score, query_id, number) for query_id, number, score in updates],
            )
        connection.commit()
        scored += len(updates)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FROM rag_citation c
              JOIN content_chunk ch ON ch.id = c.content_chunk_id
             WHERE c.support_score IS NULL
               AND length(coalesce(c.claim_text, '')) > 0
               AND length(coalesce(ch.body_text, '')) > 0
            """
        )
        remaining = int((cursor.fetchone() or (0,))[0])

    return {"scored": scored, "remaining": remaining}

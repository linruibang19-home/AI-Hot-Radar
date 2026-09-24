"""Point a citation at the chunk that says the claim, not the chunk that was found.

B5 (ADR-0016) generates from the parent block and cites the retrieval hit: "the
reader checks a paragraph; the model reads enough of the document to be right
about it". The two halves disagree whenever the model takes its fact from a
sibling. Seen on production: an answer said Opus 5.5's API price was cut to 80%
and cited 量子位's article through chunk 1 — the hit. The price is in chunk 0,
the headline; chunk 1 has no price at all. The support gate scored the claim
against the whole document (0.97) and let it through, so the reader was shown a
passage that does not contain the sentence it is supposed to back.

The generation evaluation had been measuring this all along: passage-level
support (`support_supported`, 0.9578) sits below support on the text the model
read (`support_as_read_supported`, 0.987), and the gap is these citations.

**Only where every sibling shares one parent.** In the `document` and `section`
tiers, expanding any sibling yields the same block, so moving the anchor
changes what the reader is shown and nothing about what the model read or what
the gate judged. In the `neighbours` tier each chunk has its own window, and a
move would quietly change the as-read basis the evaluation compares against.

**Only when the hit fails on its own.** A hit that already supports the claim
stays, even if a sibling scores a little higher: the citation is correct, and
swapping one supporting passage for another is churn a reader cannot see the
reason for.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ahr.rag.answer import Citation
from ahr.rag.parent import ParentBlock
from ahr.rag.rerank import RerankClient, RerankUnavailableError

logger = logging.getLogger(__name__)

ANCHOR_TIERS = frozenset({"document", "section"})

# `parent.expand` joins chunk bodies with this; offsets into the parent text
# depend on it.
_JOIN = "\n\n"


@dataclass(frozen=True)
class Siblings:
    """The chunks of one parent block the model could actually see."""

    chunk_ids: tuple[str, ...]
    texts: tuple[str, ...]


def visible_siblings(parent: ParentBlock, *, max_chars: int) -> Siblings | None:
    """Siblings whose text begins inside the part of the parent the model was given.

    The evidence is `parent.text[:max_chars]`. A chunk past that cut was never
    in the prompt, so it cannot be where the model found anything; the last
    visible chunk is clipped at the same point.
    """
    if parent.tier not in ANCHOR_TIERS or len(parent.chunk_ids) < 2:
        return None
    if len(parent.chunk_texts) != len(parent.chunk_ids):
        return None
    ids: list[str] = []
    texts: list[str] = []
    offset = 0
    for chunk_id, text in zip(parent.chunk_ids, parent.chunk_texts, strict=True):
        if offset >= max_chars:
            break
        visible = text[: max_chars - offset]
        if visible.strip():
            ids.append(chunk_id)
            texts.append(visible)
        offset += len(text) + len(_JOIN)
    if len(ids) < 2:
        return None
    return Siblings(chunk_ids=tuple(ids), texts=tuple(texts))


def pick_anchor(
    hit: str,
    chunk_ids: tuple[str, ...],
    scores: dict[int, float],
    *,
    threshold: float,
) -> str | None:
    """The sibling to move to, or None to keep the hit.

    `scores` maps an index into `chunk_ids` to the cross-encoder's score for
    (claim, that chunk). A hit that was cut from view has no score and counts
    as failing: the model cannot have read the claim there.
    """
    if not scores:
        return None
    hit_index = chunk_ids.index(hit) if hit in chunk_ids else None
    hit_score = scores.get(hit_index) if hit_index is not None else None
    if hit_score is not None and hit_score >= threshold:
        return None
    best = max(scores, key=lambda index: scores[index])
    if best == hit_index:
        return None
    if hit_score is not None and scores[best] <= hit_score:
        return None
    return chunk_ids[best]


async def choose_anchors(
    reranker: RerankClient | None,
    citations: list[Citation],
    siblings: dict[str, Siblings],
    *,
    threshold: float,
) -> dict[str, str]:
    """`hit chunk_id -> sibling chunk_id` for the citations worth moving.

    Keyed by the hit rather than the citation number because numbers are
    rewritten each time a later gate drops a citation; the hit is fixed.

    One rerank request per citation — one claim against its siblings — issued
    together, so the wall clock is one round trip. A failure keeps the hit: an
    outage must not move citations, only fail to improve them.
    """
    if reranker is None:
        return {}
    work = [
        (c.chunk_id, c.claim_text, siblings[c.chunk_id])
        for c in citations
        if c.chunk_id in siblings and c.claim_text
    ]
    if not work:
        return {}

    async def one(hit: str, claim: str, block: Siblings) -> tuple[str, str] | None:
        try:
            ranked = await reranker.rerank(claim, list(block.texts), top_n=len(block.texts))
        except RerankUnavailableError as exc:
            logger.warning("anchor selection unavailable: %s", exc)
            return None
        moved = pick_anchor(
            hit, block.chunk_ids, {index: score for index, score in ranked}, threshold=threshold
        )
        return (hit, moved) if moved else None

    results = await asyncio.gather(
        *(one(hit, claim, block) for hit, claim, block in work), return_exceptions=True
    )
    return {item[0]: item[1] for item in results if not isinstance(item, BaseException) and item}

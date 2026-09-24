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

**Only when the hit fails on its own.** A hit that already supports its
sentences stays, even if a sibling scores a little higher: the citation is
correct, and swapping one supporting passage for another is churn a reader
cannot see the reason for.

**Judged on every sentence the citation backs (ADR-0037).** The first version
used the citation's one `claim_text`; a marker is usually shared, and across
all 685 published sentence–citation pairs of the frozen run that moved
passage-level support only from 0.8613 to 0.8701. Scoring every backed sentence
reaches 0.8993.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ahr.rag.answer import Citation
from ahr.rag.parent import ParentBlock
from ahr.rag.rerank import RerankClient, RerankUnavailableError
from ahr.rag.sentence_support import cited_sentences

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


def sentences_by_citation(answer_markdown: str, citations: list[Citation]) -> dict[str, list[str]]:
    """`hit chunk_id -> every published sentence that carries its marker`.

    A citation with no marker in the prose (bound from `claims` because the
    model wrote none) falls back to its `claim_text`: that is the only
    sentence it is known to back.
    """
    by_number = {c.number: c for c in citations}
    backing: dict[str, list[str]] = {c.chunk_id: [] for c in citations}
    for sentence in cited_sentences(answer_markdown):
        for number in sentence.numbers:
            citation = by_number.get(number)
            if citation is not None:
                backing[citation.chunk_id].append(sentence.text)
    for citation in citations:
        if not backing[citation.chunk_id] and citation.claim_text:
            backing[citation.chunk_id] = [citation.claim_text]
    return backing


def pick_anchor(
    hit: str,
    chunk_ids: tuple[str, ...],
    scores: list[dict[int, float]],
    *,
    threshold: float,
) -> str | None:
    """The sibling to move to, or None to keep the hit.

    `scores` holds one mapping per sentence the citation backs, from an index
    into `chunk_ids` to the cross-encoder's score for (sentence, that chunk).

    The hit stays when it supports every one of its sentences. Otherwise the
    candidate supporting the most sentences wins, ties broken by total score,
    and it replaces the hit only if it ranks strictly higher. A hit cut from
    view has no scores and ranks lowest: the model cannot have read it.
    """
    if not scores:
        return None
    hit_index = chunk_ids.index(hit) if hit in chunk_ids else None

    def rank(index: int | None) -> tuple[int, float]:
        if index is None:
            return (0, 0.0)
        values = [sentence.get(index) for sentence in scores]
        supported = sum(1 for v in values if v is not None and v >= threshold)
        return (supported, sum(v for v in values if v is not None))

    if rank(hit_index)[0] == len(scores):
        return None
    candidates = sorted({index for sentence in scores for index in sentence})
    best = max(candidates, key=rank)
    if best == hit_index or rank(best) <= rank(hit_index):
        return None
    return chunk_ids[best]


async def choose_anchors(
    reranker: RerankClient | None,
    backing: dict[str, list[str]],
    siblings: dict[str, Siblings],
    *,
    threshold: float,
) -> dict[str, str]:
    """`hit chunk_id -> sibling chunk_id` for the citations worth moving.

    Keyed by the hit rather than the citation number because numbers are
    rewritten each time a later gate drops a citation; the hit is fixed.

    One rerank request per sentence a movable citation backs — that sentence
    against the citation's visible siblings — all issued together, so the wall
    clock is one round trip. On the frozen golden run that is 2.2 requests per
    answer. Any failed request keeps that citation's hit: an outage must not
    move citations, only fail to improve them.
    """
    if reranker is None:
        return {}
    work = [
        (hit, sentence, siblings[hit])
        for hit, sentences in backing.items()
        if hit in siblings
        for sentence in sentences
        if sentence
    ]
    if not work:
        return {}

    async def one(sentence: str, block: Siblings) -> dict[int, float]:
        ranked = await reranker.rerank(sentence, list(block.texts), top_n=len(block.texts))
        return {index: score for index, score in ranked}

    results = await asyncio.gather(
        *(one(sentence, block) for _, sentence, block in work), return_exceptions=True
    )
    per_hit: dict[str, list[dict[int, float]]] = {}
    failed: set[str] = set()
    for (hit, _, _), result in zip(work, results, strict=True):
        if isinstance(result, BaseException):
            if isinstance(result, RerankUnavailableError):
                logger.warning("anchor selection unavailable: %s", result)
            failed.add(hit)
            continue
        per_hit.setdefault(hit, []).append(result)

    moved: dict[str, str] = {}
    for hit, scores in per_hit.items():
        if hit in failed:
            continue
        target = pick_anchor(hit, siblings[hit].chunk_ids, scores, threshold=threshold)
        if target is not None:
            moved[hit] = target
    return moved

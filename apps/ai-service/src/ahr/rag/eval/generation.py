"""Generation-side evaluation: groundedness, citations, refusal, story coverage.

The retrieval evaluation (B1–B4) cannot see any of this. Recall and nDCG measure
whether the right documents reached the candidate set; they say nothing about
whether the answer that came out is supported by them. B5 and B6 in particular —
parent expansion and story folding — change *what the model reads* and *which
sources it reads*, and leave the ranking untouched, so the existing metrics move
not at all whether those steps work or are broken.

What is measured here, and with what:

    groundedness      cross-encoder score of (claim, cited passage). §10 allows
                      "NLI/cross-encoder or a controlled LLM"; the cross-encoder
                      is already integrated, costs no extra provider, and gives
                      the number `rag_citation.support_score` was defined for.
    citation coverage fraction of sentences carrying a citation marker
    citation precision fraction of cited documents that the golden set marked
                      relevant — a citation to an unrelated document is a
                      plausible-looking answer built on the wrong evidence
    story coverage    distinct events cited / distinct events among the relevant
                      items. This is the one B6 exists to move.
    refusal           refusal rate on unanswerable questions, and the reverse
                      error — refusing questions that were answerable
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from ahr.processing.llm import LlmClient
from ahr.rag.answer import Answer
from ahr.rag.embeddings import EmbeddingClient
from ahr.rag.eval.golden import GoldenQuestion, GoldenSet
from ahr.rag.rerank import RerankClient, RerankUnavailableError
from ahr.rag.service import answer_question

# A cited passage scoring below this does not visibly support its claim.
# Calibrated against nothing yet — reported alongside the raw distribution so
# the threshold can be moved once there is a reason to.
SUPPORT_THRESHOLD = 0.30

_SENTENCE_RE = re.compile(r"[^。！？\n]+[。！？]?")
_CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass
class GenerationResult:
    question_id: str
    category: str
    answerable: bool
    refused: bool
    citations: int
    must_contain_hit: float | None = None
    must_not_claim_mentions: list[str] = field(default_factory=list)
    citation_coverage: float | None = None
    citation_precision: float | None = None
    story_coverage: float | None = None
    support_mean: float | None = None
    support_supported: float | None = None
    latency_ms: int | None = None


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


def citation_coverage(answer_markdown: str) -> float | None:
    """Fraction of sentences carrying at least one citation marker.

    Bullet lists and headings count as sentences here. That understates
    coverage slightly — a heading needs no citation — and understating is the
    right direction for a metric whose failure mode is flattering itself.
    """
    sentences = split_sentences(answer_markdown)
    if not sentences:
        return None
    cited = sum(1 for s in sentences if _CITATION_RE.search(s))
    return cited / len(sentences)


def citation_precision(cited_items: list[str], relevant: frozenset[str]) -> float | None:
    """How many cited documents the golden set actually marked relevant.

    Low precision with high recall is the signature of an answer assembled from
    whatever was nearby: it reads well and cites the wrong thing.
    """
    if not cited_items:
        return None
    if not relevant:
        return None
    return sum(1 for item in cited_items if item in relevant) / len(cited_items)


def story_coverage(cited_stories: list[str | None], relevant_stories: set[str]) -> float | None:
    """Distinct events cited over distinct events among the relevant items.

    Folding is supposed to *raise* this: dropping a second article about an
    event frees a slot that another event can occupy. If folding were losing
    information instead, this is where it would show.
    """
    if not relevant_stories:
        return None
    covered = {s for s in cited_stories if s is not None} & relevant_stories
    return len(covered) / len(relevant_stories)


async def support_scores(
    reranker: RerankClient | None,
    answer: Answer,
    passages: dict[str, str],
) -> tuple[float | None, float | None]:
    """Mean support, and the fraction of citations that clear the threshold."""
    if reranker is None or not answer.citations:
        return None, None

    pairs = [
        (c.claim_text or answer.question, passages.get(c.chunk_id, "")) for c in answer.citations
    ]
    pairs = [(claim, passage) for claim, passage in pairs if passage]
    if not pairs:
        return None, None

    scores: list[float] = []
    for claim, passage in pairs:
        try:
            # One claim against one passage: the reranker's score for that pair
            # is the entailment proxy.
            result = await reranker.rerank(claim, [passage], top_n=1)
        except RerankUnavailableError:
            return None, None
        if result:
            scores.append(result[0][1])

    if not scores:
        return None, None
    supported = sum(1 for s in scores if s >= SUPPORT_THRESHOLD) / len(scores)
    return statistics.fmean(scores), supported


def _load_context(connection: Any, answer: Answer) -> tuple[dict[str, str], dict[str, str | None]]:
    """Cited passages and the story each cited item belongs to."""
    chunk_ids = [c.chunk_id for c in answer.citations]
    if not chunk_ids:
        return {}, {}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ch.id::text, ch.body_text, ci.id::text, ci.story_id::text
              FROM content_chunk ch
              JOIN content_revision cr ON cr.id = ch.content_revision_id
              JOIN content_item ci ON ci.id = cr.content_item_id
             WHERE ch.id = ANY(%s::uuid[])
            """,
            (chunk_ids,),
        )
        rows = cursor.fetchall()

    return (
        {row[0]: row[1] or "" for row in rows},
        {row[2]: row[3] for row in rows},
    )


def _relevant_stories(connection: Any, question: GoldenQuestion) -> set[str]:
    ids = sorted(question.relevant_ids)
    if not ids:
        return set()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT story_id::text FROM content_item"
            " WHERE id = ANY(%s::uuid[]) AND story_id IS NOT NULL",
            (ids,),
        )
        return {row[0] for row in cursor.fetchall()}


def score_answer(
    connection: Any,
    question: GoldenQuestion,
    answer: Answer,
) -> GenerationResult:
    passages, item_story = _load_context(connection, answer)
    cited_items = [c.content_item_id for c in answer.citations]

    result = GenerationResult(
        question_id=question.id,
        category=question.category,
        answerable=question.answerable,
        refused=answer.refused,
        citations=len(answer.citations),
        citation_coverage=citation_coverage(answer.answer_markdown),
        citation_precision=citation_precision(cited_items, question.relevant_ids),
        story_coverage=story_coverage(
            [item_story.get(item) for item in cited_items],
            _relevant_stories(connection, question),
        ),
        latency_ms=int(answer.metrics.get("total_ms") or 0),
    )

    if question.must_contain:
        hits = sum(1 for token in question.must_contain if token in answer.answer_markdown)
        result.must_contain_hit = hits / len(question.must_contain)

    # Substring matching only. A denial that names the term — "证据中未涉及
    # Qwen4-Ultra" — counts as a mention here, so this flags for review rather
    # than deciding. The strict signal is `refused`.
    result.must_not_claim_mentions = [
        token for token in question.must_not_claim if token in answer.answer_markdown
    ]
    return result


def summarise(results: list[GenerationResult]) -> dict[str, Any]:
    def mean(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return round(statistics.fmean(present), 4) if present else None

    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]

    summary: dict[str, Any] = {
        "questions": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "citation_coverage": mean([r.citation_coverage for r in answerable]),
        "citation_precision": mean([r.citation_precision for r in answerable]),
        "story_coverage": mean([r.story_coverage for r in answerable]),
        "support_mean": mean([r.support_mean for r in answerable]),
        "support_supported": mean([r.support_supported for r in answerable]),
        "must_contain_hit": mean([r.must_contain_hit for r in answerable]),
        "avg_citations": round(statistics.fmean([r.citations for r in answerable]), 2)
        if answerable
        else None,
        "latency_ms_mean": round(statistics.fmean([r.latency_ms or 0 for r in results]), 0)
        if results
        else None,
    }

    if unanswerable:
        summary["refusal_rate_on_unanswerable"] = round(
            sum(1 for r in unanswerable if r.refused) / len(unanswerable), 4
        )
        summary["forbidden_term_mentioned"] = sum(
            1 for r in unanswerable if r.must_not_claim_mentions
        )
    if answerable:
        # The reverse error: a system that refuses everything scores perfectly
        # on abstention and is useless.
        summary["over_refusal_rate"] = round(
            sum(1 for r in answerable if r.refused) / len(answerable), 4
        )

    by_category: dict[str, Any] = {}
    for category in sorted({r.category for r in results}):
        rows = [r for r in results if r.category == category and r.answerable]
        if not rows:
            continue
        by_category[category] = {
            "questions": len(rows),
            "citation_coverage": mean([r.citation_coverage for r in rows]),
            "citation_precision": mean([r.citation_precision for r in rows]),
            "support_mean": mean([r.support_mean for r in rows]),
        }

    return {"overall": summary, "by_category": by_category}


async def run_generation_eval(
    golden: GoldenSet,
    *,
    embedder: EmbeddingClient,
    reranker: RerankClient | None,
    llm: LlmClient,
    limit: int | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Answer each golden question for real, then score the answer."""
    import psycopg

    from ahr.config import get_settings

    questions = list(golden.questions)[: limit or len(golden.questions)]
    results: list[GenerationResult] = []

    for question in questions:
        answer = await answer_question(
            question.question,
            embedder=embedder,
            reranker=reranker,
            llm=llm,
            asked_at=question.asked_at,
            # The evaluation must not fill rag_query with 90 synthetic rows
            # every time it runs.
            persist=False,
        )
        with psycopg.connect(get_settings().database_url) as connection:
            scored = score_answer(connection, question, answer)
        mean_support, supported = await support_scores(
            reranker,
            answer,
            _load_context_passages(answer),
        )
        scored.support_mean = mean_support
        scored.support_supported = supported
        results.append(scored)

    return {
        "run_id": run_id or datetime.now(UTC).strftime("GEN-%Y%m%dT%H%M%SZ"),
        "config": {
            "variant": "generation",
            "llm": llm.model_name,
            "reranker": reranker.model_name if reranker else None,
            "support_threshold": SUPPORT_THRESHOLD,
            "questions": len(results),
        },
        "summary": summarise(results),
        "questions": [asdict(r) for r in results],
    }


def _load_context_passages(answer: Answer) -> dict[str, str]:
    """Cited passages, reopened for scoring.

    Kept separate from `_load_context` so support scoring can run outside the
    connection used for the deterministic checks; a single long-lived connection
    across 90 model round trips would sit idle in a transaction for minutes.
    """
    import psycopg

    from ahr.config import get_settings

    if not answer.citations:
        return {}
    with psycopg.connect(get_settings().database_url) as connection:
        passages, _ = _load_context(connection, answer)
    return passages

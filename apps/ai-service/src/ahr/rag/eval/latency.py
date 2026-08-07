"""Latency measurement (AHR-RAG-400 §14: p50/p95, token and model cost).

The only quantity the spec asks for that the project had no number at all for.
Everything else about the pipeline has been measured — Recall, MRR, nDCG,
groundedness, citation precision — while "is 10 seconds acceptable, and where
does it go" was answered with a single averaged figure taken from one question.

That gap matters for the next decision rather than for its own sake. Tuning the
fusion weights means widening candidate sets and reranking more of them, and
there is no way to say whether that is affordable without knowing which stage
already owns the budget.

Percentiles rather than means: a mean hides the tail, and the tail is what a
reader waiting on a page actually experiences.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ahr.processing.llm import LlmClient
from ahr.rag.embeddings import EmbeddingClient
from ahr.rag.eval.golden import GoldenSet
from ahr.rag.rerank import RerankClient
from ahr.rag.service import answer_question

# Stages in pipeline order, so the report reads as a timeline.
STAGES = ("plan", "embed", "dense", "sparse", "fuse", "rerank", "select", "parent", "generate")


@dataclass
class Sample:
    question_id: str
    category: str
    total_ms: int
    stages_ms: dict[str, int] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    evidence: int = 0
    refused: bool = False


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile.

    Not `statistics.quantiles`: it interpolates, and with 20-odd samples an
    interpolated p95 is a number that no request actually took.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered)) - 1))
    return ordered[index]


def summarise(samples: list[Sample]) -> dict[str, Any]:
    if not samples:
        return {"samples": 0}

    totals = [float(s.total_ms) for s in samples]
    report: dict[str, Any] = {
        "samples": len(samples),
        "end_to_end": {
            "p50_ms": round(percentile(totals, 0.50)),
            "p95_ms": round(percentile(totals, 0.95)),
            "max_ms": round(max(totals)),
            "mean_ms": round(statistics.fmean(totals)),
        },
    }

    stages: dict[str, Any] = {}
    for stage in STAGES:
        values = [float(s.stages_ms[stage]) for s in samples if stage in s.stages_ms]
        if not values:
            continue
        mean = statistics.fmean(values)
        stages[stage] = {
            "p50_ms": round(percentile(values, 0.50)),
            "p95_ms": round(percentile(values, 0.95)),
            "mean_ms": round(mean),
            # Share of the mean end-to-end time, so the report says where the
            # budget goes rather than only how long each part takes.
            "share": round(mean / statistics.fmean(totals), 3),
        }
    report["stages"] = stages

    report["tokens"] = {
        "prompt_p50": round(percentile([float(s.prompt_tokens) for s in samples], 0.50)),
        "prompt_p95": round(percentile([float(s.prompt_tokens) for s in samples], 0.95)),
        "completion_p50": round(percentile([float(s.completion_tokens) for s in samples], 0.50)),
        "total_prompt": sum(s.prompt_tokens for s in samples),
        "total_completion": sum(s.completion_tokens for s in samples),
    }

    by_category: dict[str, Any] = {}
    for category in sorted({s.category for s in samples}):
        rows = [float(s.total_ms) for s in samples if s.category == category]
        by_category[category] = {
            "samples": len(rows),
            "p50_ms": round(percentile(rows, 0.50)),
            "p95_ms": round(percentile(rows, 0.95)),
        }
    report["by_category"] = by_category
    return report


async def measure(
    golden: GoldenSet,
    *,
    embedder: EmbeddingClient,
    reranker: RerankClient | None,
    llm: LlmClient,
    limit: int = 24,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Answer a spread of questions for real and record where the time went.

    Sampled across categories rather than taking the first N: `recent_updates`
    questions filter by time and retrieve less, `explainer` questions expand
    large parents, and measuring only the first file would report one shape of
    query as if it were the system.
    """
    per_category = max(1, limit // 6)
    chosen = [
        question
        for category in sorted({q.category for q in golden.questions})
        for question in golden.by_category(category)[:per_category]
    ]

    samples: list[Sample] = []
    for question in chosen:
        answer = await answer_question(
            question.question,
            embedder=embedder,
            reranker=reranker,
            llm=llm,
            asked_at=question.asked_at,
            # A cache hit answers in ~200ms. Averaged into the percentiles it would
            # report a p50 the pipeline has never achieved.
            bypass_cache=True,
            persist=False,
        )
        metrics = answer.metrics
        samples.append(
            Sample(
                question_id=question.id,
                category=question.category,
                total_ms=int(metrics.get("total_ms") or 0),
                stages_ms={k: int(v) for k, v in (metrics.get("stages_ms") or {}).items()},
                prompt_tokens=int(metrics.get("prompt_tokens") or 0),
                completion_tokens=int(metrics.get("completion_tokens") or 0),
                evidence=int(metrics.get("evidence") or 0),
                refused=answer.refused,
            )
        )

    return {
        "run_id": run_id or datetime.now(UTC).strftime("LAT-%Y%m%dT%H%M%SZ"),
        "config": {
            "variant": "latency",
            "llm": llm.model_name,
            "reranker": reranker.model_name if reranker else None,
            "questions": len(samples),
        },
        "summary": summarise(samples),
        "samples": [
            {
                "question_id": s.question_id,
                "category": s.category,
                "total_ms": s.total_ms,
                "stages_ms": s.stages_ms,
            }
            for s in samples
        ],
    }

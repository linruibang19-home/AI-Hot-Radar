"""What the system costs and how long it takes, from live rows (T1-3).

Both numbers already existed and neither was reachable. `llm_usage` holds
provider-reported token counts — not estimates from character counts — and
`rag_query.metrics` holds a per-stage timing breakdown for every question ever
asked. One had a CLI subcommand; the other had nothing.

**Money is an estimate and says so.** The provider reports tokens, not currency,
so a price table converts. Rates live in configuration rather than in this file
because they are a contract term that changes without any code changing, and a
number hard-coded here would keep looking authoritative long after it stopped
being true. Everything derived from them is labelled as an estimate.

**Latency is measured, not estimated.** `total_ms` and `stages_ms` are wall
clock from the request that produced them, so the percentiles here are the real
distribution rather than the 24-question sample the offline latency run used.
"""

from __future__ import annotations

import os
from typing import Any

# Yuan per million tokens. Deliberately overridable: these are contract terms.
#
# The defaults are placeholders and are almost certainly not your rates — set
# LLM_PRICE_* from the provider's current price list before quoting any figure
# from this page.
DEFAULT_RATES = {
    "input": 2.0,
    "cached_input": 0.5,
    "output": 8.0,
}


def rates() -> dict[str, float]:
    def _rate(name: str, fallback: float) -> float:
        try:
            return float(os.environ.get(f"LLM_PRICE_{name.upper()}", "") or fallback)
        except ValueError:
            return fallback

    return {name: _rate(name, value) for name, value in DEFAULT_RATES.items()}


def _cost(prompt: int, completion: int, cached: int, table: dict[str, float]) -> float:
    """Cached prompt tokens bill at the cheaper rate and are *part of* prompt.

    Providers report `prompt_tokens` inclusive of the cached ones, so charging
    both at full rate would double-count the cache and make it look like it cost
    money instead of saving it.
    """
    fresh = max(prompt - cached, 0)
    return (
        fresh * table["input"] + cached * table["cached_input"] + completion * table["output"]
    ) / 1_000_000


def cost_summary(connection: Any, *, days: int = 30) -> dict[str, Any]:
    """Spend by operation, from provider-reported tokens."""
    table = rates()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT operation, model, count(*), sum(prompt_tokens), sum(completion_tokens),
                   sum(cached_tokens), count(*) FILTER (WHERE NOT succeeded),
                   round(avg(latency_ms))
              FROM llm_usage
             WHERE created_at > now() - (%s || ' days')::interval
             GROUP BY operation, model
             ORDER BY sum(prompt_tokens) + sum(completion_tokens) DESC
            """,
            (days,),
        )
        rows = cursor.fetchall()

    operations = []
    total = 0.0
    for row in rows:
        prompt, completion, cached = int(row[3] or 0), int(row[4] or 0), int(row[5] or 0)
        estimate = _cost(prompt, completion, cached, table)
        total += estimate
        operations.append(
            {
                "operation": row[0],
                "model": row[1],
                "calls": int(row[2]),
                "promptTokens": prompt,
                "completionTokens": completion,
                "cachedTokens": cached,
                "failed": int(row[6] or 0),
                "avgLatencyMs": int(row[7] or 0),
                "estimatedCny": round(estimate, 4),
                "cnyPerCall": round(estimate / row[2], 5) if row[2] else 0,
            }
        )

    return {
        "days": days,
        "rates": table,
        "ratesAreEstimates": True,
        "operations": operations,
        "totalEstimatedCny": round(total, 4),
    }


def latency_summary(connection: Any, *, days: int = 30) -> dict[str, Any]:
    """Percentiles and the stage breakdown, over every question actually asked.

    `percentile_cont` over the stored metrics rather than a fresh benchmark: a
    benchmark measures the questions someone chose to benchmark, and these are
    the questions people asked.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*),
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY (metrics->>'total_ms')::numeric),
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY (metrics->>'total_ms')::numeric),
                   max((metrics->>'total_ms')::numeric),
                   count(*) FILTER (WHERE status = 'REFUSED')
              FROM rag_query
             WHERE completed_at > now() - (%s || ' days')::interval
               AND metrics ? 'total_ms'
            """,
            (days,),
        )
        row = cursor.fetchone() or (0, None, None, None, 0)

        # Stage medians, one row per stage. Kept separate from the totals query
        # because a stage can be absent — `rerank` is missing whenever the
        # reranker was unavailable, and averaging its absence as zero would
        # report a speed-up that never happened.
        cursor.execute(
            """
            SELECT stage.key,
                   count(*),
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY stage.value::numeric)
              FROM rag_query q,
                   jsonb_each_text(q.metrics->'stages_ms') AS stage
             WHERE q.completed_at > now() - (%s || ' days')::interval
             GROUP BY stage.key
             ORDER BY 3 DESC
            """,
            (days,),
        )
        stage_rows = cursor.fetchall()

    total_queries = int(row[0] or 0)
    p50 = int(row[1] or 0)
    stages = [
        {"stage": name, "samples": int(count), "p50Ms": int(median or 0)}
        for name, count, median in stage_rows
    ]

    # Share of the median request, so the three external round trips are
    # visible as the ~99% they are.
    for stage in stages:
        stage["shareOfP50"] = round(stage["p50Ms"] / p50, 4) if p50 else 0.0

    return {
        "days": days,
        "queries": total_queries,
        "p50Ms": p50,
        "p95Ms": int(row[2] or 0),
        "maxMs": int(row[3] or 0),
        "refused": int(row[4] or 0),
        "refusalRate": round(int(row[4] or 0) / total_queries, 4) if total_queries else 0.0,
        "stages": stages,
    }


def corpus_summary(connection: Any) -> dict[str, Any]:
    """What the answers are drawn from, so the numbers above have a scale."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT (SELECT count(*) FROM content_item),
                   (SELECT count(*) FROM content_chunk),
                   (SELECT count(*) FROM content_chunk WHERE embedding IS NOT NULL),
                   (SELECT count(*) FROM source WHERE runtime_state = 'ACTIVE'),
                   (SELECT count(*) FROM rag_citation),
                   (SELECT count(*) FROM story WHERE independent_source_count > 1)
            """
        )
        row = cursor.fetchone() or (0, 0, 0, 0, 0, 0)

    return {
        "items": int(row[0]),
        "chunks": int(row[1]),
        "embedded": int(row[2]),
        "activeSources": int(row[3]),
        "citations": int(row[4]),
        "multiSourceStories": int(row[5]),
    }

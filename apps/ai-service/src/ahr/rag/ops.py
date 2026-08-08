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


def retrieval_summary(connection: Any, *, days: int = 30) -> dict[str, Any]:
    """What retrieval actually did, aggregated over real questions.

    The golden set cannot answer this and never will. It is 90 questions chosen
    in advance to cover six categories; this is every question anyone actually
    asked, which is a different population and the only one that says whether
    the design holds outside the cases it was designed against.

    Three things are worth aggregating, and they are the three the offline
    evaluation is structurally blind to:

    * **Which channel found the evidence that got cited.** The argument for
      hybrid retrieval rests on one anecdote — the NVFP4 question, dense #14 and
      keyword #1 — and an anecdote is not a rate. Counting `sparse_only` across
      real traffic turns "hybrid is necessary" from a story into a number, and
      would just as honestly report a small one.
    * **Why candidates were dropped.** "Same document over quota", "folded into
      one story" and "budget full" are different decisions, and their relative
      frequency says which stage is doing the work.
    * **How deep the cited evidence sat before reranking.** If everything cited
      was already top-3 after fusion, the cross-encoder is not earning its 28%
      of the latency budget.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(DISTINCT t.rag_query_id), count(*)
              FROM rag_trace t
              JOIN rag_query q ON q.id = t.rag_query_id
             WHERE q.created_at >= now() - make_interval(days => %s)
            """,
            (days,),
        )
        scale = cursor.fetchone() or (0, 0)

        cursor.execute(
            """
            SELECT t.outcome, count(*)
              FROM rag_trace t
              JOIN rag_query q ON q.id = t.rag_query_id
             WHERE q.created_at >= now() - make_interval(days => %s)
             GROUP BY t.outcome
             ORDER BY count(*) DESC
            """,
            (days,),
        )
        outcomes = [{"outcome": row[0], "count": int(row[1])} for row in cursor.fetchall()]

        # Channel attribution, over cited evidence only. A passage no one cited
        # says nothing about whether the channel that found it mattered.
        cursor.execute(
            """
            SELECT CASE
                       WHEN t.dense_rank IS NOT NULL AND t.sparse_rank IS NOT NULL THEN 'both'
                       WHEN t.sparse_rank IS NOT NULL THEN 'sparse_only'
                       WHEN t.dense_rank IS NOT NULL THEN 'dense_only'
                       ELSE 'unknown'
                   END AS channel,
                   count(*)
              FROM rag_trace t
              JOIN rag_query q ON q.id = t.rag_query_id
             WHERE q.created_at >= now() - make_interval(days => %s)
               AND t.outcome = 'cited'
             GROUP BY 1
            """,
            (days,),
        )
        channels = {row[0]: int(row[1]) for row in cursor.fetchall()}

        # Where the cited passages sat after fusion, before the cross-encoder
        # reordered them. A median near 1 would mean reranking changes nothing.
        cursor.execute(
            """
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY t.fused_rank),
                   max(t.fused_rank),
                   count(*) FILTER (WHERE t.fused_rank > 10)
              FROM rag_trace t
              JOIN rag_query q ON q.id = t.rag_query_id
             WHERE q.created_at >= now() - make_interval(days => %s)
               AND t.outcome = 'cited' AND t.fused_rank IS NOT NULL
            """,
            (days,),
        )
        depth = cursor.fetchone() or (None, None, 0)

    cited = sum(channels.values())
    return {
        "days": days,
        "queries": int(scale[0]),
        "candidates": int(scale[1]),
        "outcomes": outcomes,
        "citedByChannel": channels,
        # The headline: how often the keyword channel was the only one that
        # found a passage the answer went on to cite.
        "sparseOnlyShare": round(channels.get("sparse_only", 0) / cited, 4) if cited else None,
        "citedFusedRankMedian": float(depth[0]) if depth[0] is not None else None,
        "citedFusedRankMax": int(depth[1]) if depth[1] is not None else None,
        "citedBeyondTop10": int(depth[2] or 0),
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

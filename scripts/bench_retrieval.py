"""Retrieval latency benchmark, database stages only.

Runs inside the ai-service container on the production host:

    python /tmp/bench_retrieval.py embed            # once: embed the golden questions
    python /tmp/bench_retrieval.py bench --label X  # any number of times

`embed` calls the embedding provider once per question and stores the vectors.
`bench` then never leaves the database: it hands `service.retrieve` the stored
vector and no reranker, so what it times is plan, dense, sparse, temporal and
fusion — the stages database tuning can change. Embedding and rerank are
provider round trips and would only add noise to a before/after comparison.

Two things are recorded besides timings, because a faster benchmark is only an
improvement if it returns the same thing:

- a fingerprint of each question's ranked chunk ids. Tuning `random_page_cost`
  or memory can change a plan; it must not change a result. Comparing the
  fingerprints of two runs proves that, question by question.
- buffer hits and reads on `content_chunk` and its indexes during the run, so
  "it got faster" can be attributed to "it stopped reading from disk".
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from ahr.config import get_settings
from ahr.rag.eval.golden import load_golden_set

GOLDEN = Path("/app/data/golden")
VECTORS = Path("/tmp/bench_vectors.json")
RESULTS = Path("/tmp")

SETTINGS = (
    "shared_buffers",
    "effective_cache_size",
    "work_mem",
    "maintenance_work_mem",
    "random_page_cost",
    "effective_io_concurrency",
    "jit",
)


def _questions():
    return load_golden_set(GOLDEN, require_full=False).questions


async def embed() -> None:
    from ahr.rag.embeddings import build_client_from_env

    questions = _questions()
    vectors: dict[str, list[float]] = {}
    async with build_client_from_env() as client:
        for start in range(0, len(questions), 16):
            batch = questions[start : start + 16]
            for question, vector in zip(
                batch, await client.embed([q.question for q in batch]), strict=True
            ):
                vectors[question.id] = vector
    VECTORS.write_text(json.dumps(vectors))
    print(json.dumps({"embedded": len(vectors), "path": str(VECTORS)}))


def _buffer_counters(connection) -> dict[str, int]:
    row = connection.execute(
        """
        SELECT coalesce(sum(t.heap_blks_hit), 0), coalesce(sum(t.heap_blks_read), 0),
               coalesce(sum(t.idx_blks_hit), 0),  coalesce(sum(t.idx_blks_read), 0),
               coalesce(sum(t.toast_blks_hit), 0), coalesce(sum(t.toast_blks_read), 0)
          FROM pg_statio_user_tables t
         WHERE t.relname IN ('content_chunk', 'content_item', 'content_revision')
        """
    ).fetchone()
    keys = ("heap_hit", "heap_read", "idx_hit", "idx_read", "toast_hit", "toast_read")
    return dict(zip(keys, (int(v) for v in row), strict=True))


def _percentiles(values: list[int]) -> dict[str, int]:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "p50": int(statistics.median(ordered)),
        "p95": ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))],
        "max": ordered[-1],
    }


async def bench(label: str, passes: int) -> None:
    from ahr.rag.service import retrieve

    vectors = json.loads(VECTORS.read_text())
    questions = [q for q in _questions() if q.id in vectors]

    with psycopg.connect(get_settings().database_url, autocommit=True) as connection:
        settings = {
            name: connection.execute("SELECT current_setting(%s)", (name,)).fetchone()[
                0
            ]
            for name in SETTINGS
        }
        runs = []
        for number in range(1, passes + 1):
            before = _buffer_counters(connection)
            per_question = []
            for question in questions:
                stages: dict[str, int] = {}

                async def on_stage(name: str, detail: dict, _stages=stages) -> None:
                    _stages[name] = int(detail.get("ms", 0))

                started = time.monotonic()
                hits, _plan, _meta = await retrieve(
                    connection,
                    question.question,
                    embedder=None,  # type: ignore[arg-type]  # never called: query_vector is given
                    reranker=None,
                    asked_at=question.asked_at,
                    on_stage=on_stage,
                    query_vector=vectors[question.id],
                )
                wall = int((time.monotonic() - started) * 1000)
                ids = ",".join(str(getattr(h, "chunk_id", "")) for h in hits)
                per_question.append(
                    {
                        "id": question.id,
                        "category": question.category,
                        "wall_ms": wall,
                        "stages": stages,
                        "hits": len(hits),
                        "fingerprint": hashlib.sha256(ids.encode()).hexdigest()[:16],
                    }
                )
            after = _buffer_counters(connection)
            delta = {k: after[k] - before[k] for k in before}
            hit = delta["heap_hit"] + delta["idx_hit"] + delta["toast_hit"]
            read = delta["heap_read"] + delta["idx_read"] + delta["toast_read"]
            stage_names = sorted({s for q in per_question for s in q["stages"]})
            runs.append(
                {
                    "pass": number,
                    "wall": _percentiles([q["wall_ms"] for q in per_question]),
                    "stages": {
                        s: _percentiles(
                            [q["stages"][s] for q in per_question if s in q["stages"]]
                        )
                        for s in stage_names
                    },
                    "buffers": {
                        **delta,
                        "hit_ratio": round(hit / (hit + read), 4)
                        if hit + read
                        else None,
                    },
                    "questions": per_question,
                }
            )

    result = {
        "label": label,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "questions": len(questions),
        "settings": settings,
        "runs": runs,
    }
    out = RESULTS / f"bench-{label}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    summary = {k: v for k, v in result.items() if k != "runs"}
    summary["runs"] = [{k: v for k, v in r.items() if k != "questions"} for r in runs]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("embed")
    b = sub.add_parser("bench")
    b.add_argument("--label", required=True)
    b.add_argument("--passes", type=int, default=2)
    args = parser.parse_args()
    if args.mode == "embed":
        asyncio.run(embed())
    else:
        asyncio.run(bench(args.label, args.passes))
    return 0


if __name__ == "__main__":
    sys.exit(main())

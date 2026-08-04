"""Reciprocal rank fusion and the bounded metadata boosts of AHR-RAG-400 §6.

Why RRF rather than a weighted sum of scores: the channels are not on the same
scale and cannot be put on one. Dense retrieval returns cosine similarity;
`ts_rank_cd` is not BM25 and carries no IDF. Normalising them would invent a
comparison that does not exist.

B2 measured what happens without a real fusion. Merging the two channels by
round-robin — which hands the weaker channel half the slots unconditionally —
made **every** headline metric worse than dense alone (Recall@10 0.8045 →
0.7637), and on one question the merge scored below *both* of its inputs. RRF is
therefore a requirement rather than a refinement, and it has a number to beat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ahr.rag.retrieval import ChunkHit

# AHR-RAG-400 §6: rrf(d) = Σ weight(channel) / (K + rank_channel(d))
RRF_K = 60

# Dense carries the general case; sparse is a precision instrument for rare
# tokens. B2 measured sparse-only Recall@20 at 0.4662 against dense's 0.8876,
# so an equal split would repeat the interleave regression.
#
# `temporal` is far lower still, and the first run of B3 is why. It was missing
# from this table, `.get(channel, 1.0)` handed it the same weight as dense, and
# forty chunks ordered by nothing but recency flooded the top of every
# time-scoped question: Recall@10 fell from 0.8045 to 0.3643. A channel with no
# relevance signal contributes coverage, not rank.
#
# Swept against the golden set (42 combinations, `eval/sweep.py`) and kept.
#
# The sweep found a better *fused* order — sparse 0.2 / temporal 0.4 scored MRR
# 0.7362 against these weights' 0.6770 — and running both through the full
# pipeline showed the reranker erases the entire difference: MRR 0.8645 vs
# 0.8641, with four of six categories identical rank for rank. Shipping the
# sweep winner on its pre-rerank number would have claimed a 5.9-point gain that
# does not exist end to end.
#
# What the grid does establish is that 0.6 sits on a plateau rather than a
# cliff: Recall@40 varies by 0.0043 across the whole grid, while sparse >= 0.8
# starts destroying Recall@20 (0.8833 -> 0.8124 at 1.2). Tuning these further is
# not a lever on this system; the reranker owns the ordering.
DEFAULT_WEIGHTS = {"dense": 1.0, "sparse": 0.6, "temporal": 0.15}

# §6 fixes these magnitudes. They are bounded on purpose: a boost large enough
# to reorder the top of the list would make the metadata, not the question,
# decide the answer.
BOOST_PRIMARY_SOURCE = 0.08
BOOST_IN_TIME_WINDOW = 0.05
BOOST_ENTITY_SUBJECT = 0.05
PENALTY_REPOST = -0.10
PENALTY_OPINION_FOR_FACT = -0.15


@dataclass
class FusedHit:
    chunk_id: str
    content_item_id: str
    score: float
    title: str
    source_name: str
    channels: tuple[str, ...]
    boosts: tuple[str, ...] = ()


def reciprocal_rank_fusion(
    channels: dict[str, list[ChunkHit]],
    *,
    weights: dict[str, float] | None = None,
    k: int = RRF_K,
) -> list[FusedHit]:
    """Fuse ranked channel outputs on rank alone.

    A chunk found by both channels accumulates both contributions, which is the
    property the round-robin merge lacked: agreement between an independent
    semantic match and an exact-token match is evidence, and RRF is what turns
    it into rank.
    """
    resolved = weights or DEFAULT_WEIGHTS
    scores: dict[str, float] = {}
    found_in: dict[str, list[str]] = {}
    seen: dict[str, ChunkHit] = {}

    for channel, hits in channels.items():
        weight = resolved.get(channel, 1.0)
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + weight / (k + rank)
            found_in.setdefault(hit.chunk_id, []).append(channel)
            seen.setdefault(hit.chunk_id, hit)

    fused = [
        FusedHit(
            chunk_id=chunk_id,
            content_item_id=seen[chunk_id].content_item_id,
            score=score,
            title=seen[chunk_id].title,
            source_name=seen[chunk_id].source_name,
            channels=tuple(found_in[chunk_id]),
        )
        for chunk_id, score in scores.items()
    ]
    # Ties broken by chunk id so a run is reproducible; an arbitrary tie order
    # would make two evaluation runs differ for no reason.
    fused.sort(key=lambda hit: (-hit.score, hit.chunk_id))
    return fused


def apply_boosts(
    hits: list[FusedHit],
    metadata: dict[str, dict[str, object]],
    *,
    query_type: str,
    window: tuple[datetime, datetime] | None,
    query_entities: frozenset[str] = frozenset(),
) -> list[FusedHit]:
    """Bounded metadata adjustments (§6), applied to a normalised score.

    `metadata` maps content_item_id to `source_tier`, `content_type` and
    `published_at`. Each signal is applied at most once — §6 forbids counting
    the same signal twice, which is how boost stacking quietly becomes the
    ranking function.

    The normalisation is not cosmetic. A raw RRF score lives around
    1/(60+rank) ≈ 0.008–0.017, while §6 specifies boosts of ±0.05 to ±0.15 —
    **five to ten times the entire spread of the thing being boosted**. Applied
    directly they stop being adjustments and become the ranking: the first B3
    run put every primary source above every secondary one regardless of
    relevance, and `fact_check` Recall@10 fell from 0.9556 to 0.2556.
    §6's magnitudes only mean what they say on a [0, 1] scale, so the fused
    score is mapped onto one first.
    """
    if not hits:
        return hits

    scores = [hit.score for hit in hits]
    low, high = min(scores), max(scores)
    spread = high - low
    for hit in hits:
        hit.score = (hit.score - low) / spread if spread > 0 else 1.0

    for hit in hits:
        meta = metadata.get(hit.content_item_id)
        if not meta:
            continue

        applied: list[str] = []

        if meta.get("source_tier") == "primary":
            hit.score += BOOST_PRIMARY_SOURCE
            applied.append("primary_source")

        published = meta.get("published_at")
        if window and isinstance(published, datetime) and window[0] <= published < window[1]:
            hit.score += BOOST_IN_TIME_WINDOW
            applied.append("in_time_window")

        # "直接命中目标实体为主语". A release note whose *subject* is the model
        # being asked about answers the question; one that lists it among
        # supported formats mentions it. `role` already draws that line, and
        # `directness` (B9) draws a related one from the title — they agree
        # often but not always, which is why both exist.
        subjects = meta.get("subject_entities")
        if query_entities and isinstance(subjects, frozenset) and (subjects & query_entities):
            hit.score += BOOST_ENTITY_SUBJECT
            applied.append("entity_subject")

        # "重复转载". Near-duplicates were chunked before dedup marked them, so
        # 516 chunks in this corpus belong to items that are copies of another
        # item already in the index. Demoting rather than excluding: the copy is
        # still evidence if the original happens to be missing.
        if meta.get("is_repost"):
            hit.score += PENALTY_REPOST
            applied.append("repost")

        if query_type == "fact_check" and meta.get("content_type") == "opinion":
            hit.score += PENALTY_OPINION_FOR_FACT
            applied.append("opinion_for_fact")

        hit.boosts = tuple(applied)

    hits.sort(key=lambda hit: (-hit.score, hit.chunk_id))
    return hits

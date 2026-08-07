"""Retrieval channels (M4).

`VECTOR_PASSAGE` and `KEYWORD_FTS`. AHR-ROADMAP-800 TASK-M4-001 requires the
dense baseline to be measured before anything is layered on top, so each
channel arrives with a number attached rather than an impression.

Channel topK defaults follow AHR-RAG-400 §5, which also states that the values
must be tuned against the evaluation set rather than treated as constants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# AHR-RAG-400 §5: VECTOR_PASSAGE topK. Chosen there, to be re-tuned here.
VECTOR_PASSAGE_TOP_K = 60

# AHR-RAG-400 §5: KEYWORD_FTS topK.
KEYWORD_FTS_TOP_K = 40

# AHR-RAG-400 §5: TEMPORAL_SQL topK.
TEMPORAL_SQL_TOP_K = 40

# A lexeme present in more than this share of chunks carries no retrieval
# signal. Deriving the cut-off from the corpus rather than from a stopword list
# is what lets one rule serve both languages: "的" and "the" are dropped for the
# same measured reason, and a term that is common in AI news but rare in English
# generally — "model", "release" — is dropped here even though no stopword list
# would contain it.
MAX_DOCUMENT_FREQUENCY_RATIO = 0.15


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: str
    content_item_id: str
    score: float
    title: str
    source_name: str


def dense_search(
    connection: Any,
    query_vector: list[float],
    *,
    limit: int = VECTOR_PASSAGE_TOP_K,
    window: tuple[datetime, datetime] | None = None,
) -> list[ChunkHit]:
    """Nearest chunks by cosine distance, newest revision only.

    `<=>` is pgvector's cosine distance, so similarity is `1 - distance`. The
    HNSW index built in V012 uses `vector_cosine_ops`; using any other operator
    here would silently fall back to a sequential scan.

    Restricting to `content_item.current_revision_id` matters for changelog
    sources, which are re-fetched and re-chunked whenever the page changes: old
    revisions keep their chunks and would otherwise return stale passages that
    no longer exist on the page being cited.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ch.id::text,
                   ci.id::text,
                   1 - (ch.embedding <=> %s::vector) AS similarity,
                   COALESCE(ci.zh_title, ci.title),
                   s.name
              FROM content_chunk ch
              JOIN content_revision cr ON cr.id = ch.content_revision_id
              JOIN content_item ci ON ci.id = cr.content_item_id
                                  AND ci.current_revision_id = cr.id
              JOIN source s ON s.id = ci.source_id
             WHERE ch.embedding IS NOT NULL
               AND ci.duplicate_of_id IS NULL
               AND (%s::timestamptz IS NULL
                    OR COALESCE(ci.published_at, ci.observed_at) >= %s)
               AND (%s::timestamptz IS NULL
                    OR COALESCE(ci.published_at, ci.observed_at) < %s)
             ORDER BY ch.embedding <=> %s::vector
             LIMIT %s
            """,
            (
                str(query_vector),
                window[0] if window else None,
                window[0] if window else None,
                window[1] if window else None,
                window[1] if window else None,
                str(query_vector),
                limit,
            ),
        )
        return [
            ChunkHit(
                chunk_id=row[0],
                content_item_id=row[1],
                score=float(row[2]),
                title=row[3] or "",
                source_name=row[4] or "",
            )
            for row in cursor.fetchall()
        ]


def temporal_search(
    connection: Any,
    *,
    window: tuple[datetime, datetime],
    limit: int = TEMPORAL_SQL_TOP_K,
    content_type: str | None = None,
) -> list[ChunkHit]:
    """Chunks from items published inside the window, newest first.

    No semantic component at all, and that is the point. B1 measured
    `recent_updates` as the weakest category (Recall@10 0.619, MRR 0.468) with
    the first relevant document as low as rank 17, because a dense vector cannot
    express "last week". This channel contributes the axis the other two lack;
    fusion is what combines it with relevance.

    One chunk per item — the leading one. A day's worth of release notes would
    otherwise flood the candidate set with fifty chunks of one changelog, which
    is the same monopolisation the item-level scoring exists to prevent.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (ci.id)
                   ch.id::text,
                   ci.id::text,
                   COALESCE(ci.published_at, ci.observed_at),
                   COALESCE(ci.zh_title, ci.title),
                   s.name
              FROM content_item ci
              JOIN content_revision cr ON cr.id = ci.current_revision_id
              JOIN content_chunk ch ON ch.content_revision_id = cr.id
              JOIN source s ON s.id = ci.source_id
             WHERE ci.duplicate_of_id IS NULL
               AND COALESCE(ci.published_at, ci.observed_at) >= %s
               AND COALESCE(ci.published_at, ci.observed_at) < %s
               AND (%s::text IS NULL OR ci.content_type = %s)
             ORDER BY ci.id, ch.ordinal
            """,
            (window[0], window[1], content_type, content_type),
        )
        rows = cursor.fetchall()

    # Ordered outside SQL because DISTINCT ON dictates its own ORDER BY.
    rows.sort(key=lambda row: row[2], reverse=True)
    return [
        ChunkHit(
            chunk_id=row[0],
            content_item_id=row[1],
            # Rank is the signal here; RRF reads position, not score. A fake
            # similarity would be a number nobody should compare against.
            score=0.0,
            title=row[3] or "",
            source_name=row[4] or "",
        )
        for row in rows[:limit]
    ]


def load_chunk_texts(connection: Any, chunk_ids: list[str]) -> dict[str, str]:
    """Body text for reranking, with the same context header used at index time.

    The cross-encoder has to see what the bi-encoder saw. A bare changelog
    bullet — "- Authenticate skill registry downloads" — is as unrankable as it
    was unsearchable, and scoring it without its product and release would make
    the reranker worse than the retrieval it is correcting.

    The header is composed here rather than stored, exactly as in `context.py`:
    `body_text` stays verbatim so a citation remains checkable against the
    original.
    """
    if not chunk_ids:
        return {}

    from ahr.rag.context import build_embedding_text

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ch.id::text, ch.body_text, ch.heading_path,
                   COALESCE(ci.zh_title, ci.title), s.name,
                   COALESCE(ci.published_at, ci.observed_at)
              FROM content_chunk ch
              JOIN content_revision cr ON cr.id = ch.content_revision_id
              JOIN content_item ci ON ci.id = cr.content_item_id
              JOIN source s ON s.id = ci.source_id
             WHERE ch.id = ANY(%s::uuid[])
            """,
            (chunk_ids,),
        )
        return {
            row[0]: build_embedding_text(
                body_text=row[1],
                heading_path=list(row[2] or []),
                title=row[3],
                source_name=row[4],
                published_at=row[5],
            )
            for row in cursor.fetchall()
        }


def load_item_metadata(connection: Any, item_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Source tier, content type, publication time and §6's two structural flags.

    `subject_entities` and `is_repost` are the inputs to the boosts that were
    left unimplemented the first time round, on the belief that the data was not
    available. It was: `item_entity.role` distinguishes subject from mention,
    and near-duplicate detection already sets `duplicate_of_id`.
    """
    if not item_ids:
        return {}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.id::text, s.source_tier, ci.content_type,
                   COALESCE(ci.published_at, ci.observed_at),
                   ci.duplicate_of_id IS NOT NULL,
                   COALESCE(
                       array_agg(ie.entity_id::text) FILTER (WHERE ie.entity_id IS NOT NULL),
                       '{}'
                   )
              FROM content_item ci
              JOIN source s ON s.id = ci.source_id
              LEFT JOIN item_entity ie
                     ON ie.content_item_id = ci.id AND ie.role = 'subject'
             WHERE ci.id = ANY(%s::uuid[])
             GROUP BY ci.id, s.source_tier, ci.content_type, ci.published_at, ci.observed_at
            """,
            (item_ids,),
        )
        return {
            row[0]: {
                "source_tier": row[1],
                "content_type": row[2],
                "published_at": row[3],
                "is_repost": bool(row[4]),
                "subject_entities": frozenset(row[5] or ()),
            }
            for row in cursor.fetchall()
        }


# A one- or two-letter Latin "entity" matches inside ordinary words — the corpus
# genuinely contains entities named `ai` and `X`, and boosting every question
# that mentions AI would make the signal noise. CJK is denser: 微软 is
# unambiguous at two characters.
MIN_LATIN_ENTITY_CHARS = 3
MIN_CJK_ENTITY_CHARS = 2

_CJK_CHAR = re.compile(r"[一-鿿぀-ヿ]")


def resolve_query_entities(connection: Any, question: str) -> frozenset[str]:
    """Entity ids named in the question, drawn from the corpus's own vocabulary.

    Matching against the entity table rather than running NER: the only
    entities that can affect ranking are ones the corpus already knows about,
    and the table is the exact list of those. It also means the resolver
    inherits whatever the enrichment step learned, with no second model to keep
    in agreement with the first.
    """
    if not question.strip():
        return frozenset()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id::text, name
              FROM entity
             WHERE length(name) >= %s
               AND position(lower(name) in lower(%s)) > 0
            """,
            (MIN_CJK_ENTITY_CHARS, question),
        )
        candidates = cursor.fetchall()

    lowered = question.lower()
    resolved: set[str] = set()
    for entity_id, name in candidates:
        if _CJK_CHAR.search(name):
            resolved.add(entity_id)
            continue
        # Latin needs a word boundary: without it `Qwen` matches inside
        # `Qwen3.8-Max` — fine — but `ERA` also matches inside `general`.
        if len(name) < MIN_LATIN_ENTITY_CHARS:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", lowered):
            resolved.add(entity_id)
    return frozenset(resolved)


def _escape_lexeme(lexeme: str) -> str:
    """Quote a lexeme for inclusion in a tsquery."""
    return "'" + lexeme.replace("'", "''") + "'"


# CJK adjacent to Latin/digits, in either order.
_SCRIPT_BOUNDARY = re.compile(r"(?<=[一-鿿぀-ヿ])(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])(?=[一-鿿぀-ヿ])")


def split_scripts(text: str) -> str:
    """Insert a space at every CJK/Latin boundary.

    Postgres's `simple` parser splits on whitespace and punctuation, not on
    script changes, so `最近grok有什么动态吗` — typed exactly as a Chinese
    speaker types it — becomes **one** lexeme. That glued token appears nowhere
    in the corpus, `select_query_terms` finds nothing above zero frequency, and
    the sparse channel silently returns zero hits.

    The effect is worse than the CJK gap recorded in ADR-0015. It is not only
    that `智谱` misses the token `智谱发布`; it is that **any Latin product name
    written inline in a Chinese sentence is invisible to keyword retrieval** —
    and that is the most common shape of question this product receives. It hid
    because dense retrieval still returned 60 candidates, so the answer looked
    reasonable while running on one channel instead of two.

    Splitting the *query* only. The index is built from `body_text`, where the
    same names are already surrounded by spaces or punctuation in prose; the
    asymmetry is the point.
    """
    return _SCRIPT_BOUNDARY.sub(" ", text)


def select_query_terms(
    connection: Any,
    question: str,
    *,
    max_df_ratio: float = MAX_DOCUMENT_FREQUENCY_RATIO,
) -> list[tuple[str, int]]:
    """Distinctive lexemes from the question, with their document frequency.

    Two things make this necessary rather than decorative.

    First, `plainto_tsquery` ANDs every term, and a natural-language question
    ANDed against a passage matches nothing: measured on this corpus, the
    question "使用 MXFP4 量化的是哪个模型？" returns **zero** rows that way,
    while the term `mxfp4` alone matches 30 chunks. The channel has to OR.

    Second, ORing *everything* is just as bad in the other direction. Postgres
    full-text ranking has no IDF — `ts_rank_cd` is not BM25 — so a common term
    contributes as much as a rare one and drowns it. Document frequency is
    therefore measured here and used to drop terms the corpus says are common.

    Tokenisation is delegated to Postgres so query and index agree by
    construction — the same `ahr_cjk_bigrams` the stored vectors are built from
    is applied to the question here. A Python-side segmenter would have been
    easier and would have broken that property the first time either side
    changed.

    The CJK bigrams are what make the channel work in Chinese at all. Without
    them a run of Chinese became a single lexeme ("量化的是哪个模型") with a
    document frequency of zero, so it was dropped and the question fell back to
    whatever ASCII it happened to contain — Recall@20 0.0588 on purely Chinese
    questions against 0.5798 on ones with an ASCII proper noun (B2). Bigrams
    over-generate, and the document-frequency ceiling below already removes what
    that produces: a bigram spanning a word boundary is either very common or
    absent, and both are dropped. That filter was written to avoid needing a
    stop-word list; it turns out to serve this too.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM content_chunk WHERE search_vector IS NOT NULL")
        total = cursor.fetchone()[0] or 0
        if total == 0:
            return []

        cursor.execute(
            """
            WITH terms AS (
                SELECT DISTINCT lexeme
                  FROM unnest(
                           to_tsvector('simple', %s)
                           || to_tsvector('simple', ahr_cjk_bigrams(%s))
                       )
            )
            SELECT t.lexeme,
                   (SELECT count(*)
                      FROM content_chunk c
                     WHERE c.search_vector @@ plainto_tsquery('simple', t.lexeme)) AS df
              FROM terms t
            """,
            (split_scripts(question), question),
        )
        rows = cursor.fetchall()

    ceiling = max(1, int(total * max_df_ratio))
    kept = [(str(lexeme), int(df)) for lexeme, df in rows if 0 < int(df) <= ceiling]
    # Rarest first: if the query has to be truncated, the discriminating terms
    # are the ones worth keeping.
    kept.sort(key=lambda pair: pair[1])
    return kept


def sparse_search(
    connection: Any,
    question: str,
    *,
    limit: int = KEYWORD_FTS_TOP_K,
    max_df_ratio: float = MAX_DOCUMENT_FREQUENCY_RATIO,
    window: tuple[datetime, datetime] | None = None,
) -> list[ChunkHit]:
    """Keyword retrieval over the GIN index built in V001.

    Returns nothing when the question contains no distinctive term — for a
    purely conversational question that is the correct answer, and silently
    falling back to a match-anything query would fill the candidate set with
    noise that the fusion step would then have to undo.
    """
    terms = select_query_terms(connection, question, max_df_ratio=max_df_ratio)
    if not terms:
        return []

    tsquery = " | ".join(_escape_lexeme(lexeme) for lexeme, _ in terms)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ch.id::text,
                   ci.id::text,
                   ts_rank_cd(ch.search_vector, q) AS rank,
                   COALESCE(ci.zh_title, ci.title),
                   s.name
              FROM to_tsquery('simple', %s) AS q
              JOIN content_chunk ch ON ch.search_vector @@ q
              JOIN content_revision cr ON cr.id = ch.content_revision_id
              JOIN content_item ci ON ci.id = cr.content_item_id
                                  AND ci.current_revision_id = cr.id
              JOIN source s ON s.id = ci.source_id
             WHERE ci.duplicate_of_id IS NULL
               AND (%s::timestamptz IS NULL
                    OR COALESCE(ci.published_at, ci.observed_at) >= %s)
               AND (%s::timestamptz IS NULL
                    OR COALESCE(ci.published_at, ci.observed_at) < %s)
             ORDER BY rank DESC, ch.id
             LIMIT %s
            """,
            (
                tsquery,
                window[0] if window else None,
                window[0] if window else None,
                window[1] if window else None,
                window[1] if window else None,
                limit,
            ),
        )
        return [
            ChunkHit(
                chunk_id=row[0],
                content_item_id=row[1],
                score=float(row[2]),
                title=row[3] or "",
                source_name=row[4] or "",
            )
            for row in cursor.fetchall()
        ]


def interleave(*channels: list[ChunkHit]) -> list[ChunkHit]:
    """Round-robin the channels, dropping chunks already taken.

    Deliberately naive. B2 exists to answer one question — does the sparse
    channel put documents into the candidate set that the dense channel misses
    — and a real fusion would confound that with a ranking change. Weighted RRF
    (AHR-RAG-400 §6) arrives in B3 and has to beat this.
    """
    seen: set[str] = set()
    merged: list[ChunkHit] = []
    for position in range(max((len(channel) for channel in channels), default=0)):
        for channel in channels:
            if position >= len(channel):
                continue
            hit = channel[position]
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            merged.append(hit)
    return merged

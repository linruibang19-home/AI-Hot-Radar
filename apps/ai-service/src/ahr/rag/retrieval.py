"""Retrieval channels (M4).

`VECTOR_PASSAGE` and `KEYWORD_FTS`. AHR-ROADMAP-800 TASK-M4-001 requires the
dense baseline to be measured before anything is layered on top, so each
channel arrives with a number attached rather than an impression.

Channel topK defaults follow AHR-RAG-400 §5, which also states that the values
must be tuned against the evaluation set rather than treated as constants.
"""

from __future__ import annotations

import math
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

# How much more a lexeme is worth when the corpus knows it as an entity.
#
# IDF alone cannot separate 智谱 from 了什 on this corpus, and the reason is
# specific: the bodies are mostly English, so *any* Chinese bigram is rare
# corpus-wide. Measured on 「智谱最近发布了什么」 —
#
#     智谱 df=3 idf=7.66      了什 df=18 idf=5.87
#     zhipu df=4 idf=7.37     布了 df=23 idf=5.62
#
# and `了什` / `布了` are not words at all, they are ADR-0018's bigrams crossing
# word boundaries in 「发布了什么」. Five of those sum to 25.96 and outrank the one
# term naming the vendor. The df ceiling cannot fix it either: these lexemes are
# genuinely rare by the measure it uses.
#
# What separates them is not frequency but status — one is a name the corpus has
# an `entity` row for, the others are fragments. So the entity terms are weighted
# rather than the fragments filtered, which needs no list of stop-bigrams and no
# segmenter.
ENTITY_TERM_WEIGHT = 3.0


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: str
    content_item_id: str
    score: float
    title: str
    source_name: str
    source_id: str = ""
    source_tier: str = ""
    channels: tuple[str, ...] = ()


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
                   s.name,
                   s.id,
                   s.source_tier
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
                source_id=row[5] or "",
                source_tier=row[6] or "",
            )
            for row in cursor.fetchall()
        ]


def temporal_search(
    connection: Any,
    *,
    window: tuple[datetime, datetime],
    limit: int = TEMPORAL_SQL_TOP_K,
    content_type: str | None = None,
    entity_ids: frozenset[str] = frozenset(),
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
                   s.name,
                   s.id,
                   s.source_tier
              FROM content_item ci
              JOIN content_revision cr ON cr.id = ci.current_revision_id
              JOIN content_chunk ch ON ch.content_revision_id = cr.id
              JOIN source s ON s.id = ci.source_id
             WHERE ci.duplicate_of_id IS NULL
               AND COALESCE(ci.published_at, ci.observed_at) >= %s
               AND COALESCE(ci.published_at, ci.observed_at) < %s
               AND (%s::text IS NULL OR ci.content_type = %s)
               AND (cardinality(%s::uuid[]) = 0 OR EXISTS (
                    SELECT 1
                      FROM item_entity ie
                     WHERE ie.content_item_id = ci.id
                       AND ie.role = 'subject'
                       AND ie.entity_id = ANY(%s::uuid[])
               ))
             ORDER BY ci.id, ch.ordinal
            """,
            (
                window[0],
                window[1],
                content_type,
                content_type,
                sorted(entity_ids),
                sorted(entity_ids),
            ),
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
            source_id=row[5] or "",
            source_tier=row[6] or "",
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
    matched: list[tuple[str, str]] = []
    for entity_id, name in candidates:
        if _CJK_CHAR.search(name):
            matched.append((entity_id, name))
            continue
        # Latin needs a word boundary: without it `Qwen` matches inside
        # `Qwen3.8-Max` — fine — but `ERA` also matches inside `general`.
        if len(name) < MIN_LATIN_ENTITY_CHARS:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", lowered):
            matched.append((entity_id, name))

    # Keep the longest name where one match is contained in another. `llama.cpp`
    # matches both `Llama` and `llama.cpp`, and the two mean different things:
    # `Llama` belongs to Meta's vendor group, so keeping it expanded a question
    # about a community C++ project into a search for Facebook and Meta AI.
    # Measured on the live corpus the moment vendor expansion was switched on.
    #
    # The word boundary is what lets this happen at all — `.` is not [a-z0-9],
    # so `llama` legitimately "ends" inside `llama.cpp`. Tightening the boundary
    # would break `Qwen` matching `Qwen3.8-Max`, which is wanted. Preferring the
    # longer name keeps both.
    names = {name.lower() for _, name in matched}
    resolved = {
        entity_id
        for entity_id, name in matched
        if not any(other != name.lower() and name.lower() in other for other in names)
    }
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


def expand_vendor_aliases(connection: Any, entity_ids: frozenset[str]) -> list[str]:
    """Other names for the same vendor, from the curated `vendor_entity` map.

    The failure this exists for, measured on the live corpus: asked
    「智谱最近发布了什么？」 the answer was **「智谱没有发布任何新模型或产品更新」**
    while the window held three Zhipu items — because the one titled
    「GLM-5.2 量化模型发布」 never contains the string 智谱, and keyword retrieval
    matches strings. The system asserted absence, which for a product whose
    claim is verifiability is worse than a hallucination.

    `vendor_entity` already groups them (`zhipu` → GLM, GLM-4.6, GLM 5.2,
    Zhipu), built for the vendor cards in V017. Reusing it rather than adding an
    alias column means one curated list serves both, and a vendor page that
    looks right is evidence the expansion will be right.

    **Curation is incomplete and that is visible, not hidden**: `llama.cpp`
    (100 items), `vLLM`, `Cloudflare` and others belong to no vendor at all, so
    they expand to nothing and behave exactly as before. Expansion helps where
    the map is filled in and is inert everywhere else — no query gets worse for
    a missing row.
    """
    if not entity_ids:
        return []

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT sibling.name
              FROM entity hit
              JOIN vendor_entity mine ON mine.entity_slug = hit.slug
              JOIN vendor_entity theirs ON theirs.vendor_slug = mine.vendor_slug
              JOIN entity sibling ON sibling.slug = theirs.entity_slug
             WHERE hit.id = ANY(%s::uuid[])
               AND sibling.id <> ALL(%s::uuid[])
            """,
            (sorted(entity_ids), sorted(entity_ids)),
        )
        names = [str(row[0]) for row in cursor.fetchall() if row[0]]

    # Collapse versions onto the family name. The aliases are appended to the
    # question and re-tokenised by Postgres, and a hyphenated name does not
    # survive that: `GLM-4.6` becomes the lexemes `glm` and `-4.6`, `GLM 5.2`
    # becomes `5.2`. Ten version rows therefore contributed one useful term and
    # nine numeric fragments, and `-4.6` matches 68 chunks that have nothing to
    # do with the vendor.
    #
    # Keeping only names no other alias is a prefix of leaves `GLM`, `Zhipu`,
    # `ZhiPuAi`, `智谱AI` — the forms a document actually spells out.
    lowered = sorted((name.lower(), name) for name in names)
    return [
        name
        for low, name in lowered
        if not any(other != low and low.startswith(other) for other, _ in lowered)
    ]


def expand_vendor_entity_ids(connection: Any, entity_ids: frozenset[str]) -> frozenset[str]:
    """Resolved entities plus every curated entity in the same vendor family.

    Text aliases help the sparse channel only when the body spells a family
    token.  The temporal SQL channel can use the stronger structured fact:
    enrichment marked the item entity as its subject.  This is what lets a
    question about 智谱 retrieve a release whose subject is ``GLM 5.2`` even
    when the publisher never writes the vendor name.
    """
    if not entity_ids:
        return entity_ids
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT sibling.id::text
              FROM entity hit
              JOIN vendor_entity mine ON mine.entity_slug = hit.slug
              JOIN vendor_entity theirs ON theirs.vendor_slug = mine.vendor_slug
              JOIN entity sibling ON sibling.slug = theirs.entity_slug
             WHERE hit.id = ANY(%s::uuid[])
            """,
            (sorted(entity_ids),),
        )
        siblings = {str(row[0]) for row in cursor.fetchall() if row[0]}
    return frozenset(set(entity_ids) | siblings)


def entity_names(connection: Any, entity_ids: frozenset[str]) -> list[str]:
    """Names for resolved entity ids, for weighting the keyword channel."""
    if not entity_ids:
        return []
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM entity WHERE id = ANY(%s::uuid[])", (sorted(entity_ids),))
        return [str(row[0]) for row in cursor.fetchall() if row[0]]


def sparse_search(
    connection: Any,
    question: str,
    *,
    limit: int = KEYWORD_FTS_TOP_K,
    max_df_ratio: float = MAX_DOCUMENT_FREQUENCY_RATIO,
    window: tuple[datetime, datetime] | None = None,
    extra_terms: list[str] | None = None,
    entity_terms: list[str] | None = None,
) -> list[ChunkHit]:
    """Keyword retrieval over the GIN index built in V001.

    Returns nothing when the question contains no distinctive term — for a
    purely conversational question that is the correct answer, and silently
    falling back to a match-anything query would fill the candidate set with
    noise that the fusion step would then have to undo.

    `extra_terms` carries vendor aliases resolved from the question's entities.
    They are ORed in like any other term and pass through the same
    document-frequency filter, so an alias common enough to be noise is dropped
    on the same rule as a common word — the expansion cannot smuggle past the
    guard that keeps this channel precise.
    """
    text = question if not extra_terms else question + " " + " ".join(extra_terms)
    terms = select_query_terms(connection, text, max_df_ratio=max_df_ratio)
    if not terms:
        return []

    tsquery = " | ".join(_escape_lexeme(lexeme) for lexeme, _ in terms)

    # ln(N/df), the standard IDF. `select_query_terms` already dropped df == 0
    # and anything above the ceiling, so every value here is finite and positive.
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM content_chunk WHERE search_vector IS NOT NULL")
        total = cursor.fetchone()[0] or 1
    lexemes = [lexeme for lexeme, _ in terms]
    # Lexemes contributed by a resolved entity or one of its vendor aliases.
    # Tokenised through the same path as the query so the two agree by
    # construction rather than by string comparison.
    entity_lexemes: set[str] = set()
    if entity_terms:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT lexeme FROM unnest(to_tsvector('simple', %s))",
                (split_scripts(" ".join(entity_terms)),),
            )
            entity_lexemes = {str(row[0]) for row in cursor.fetchall()}

    idfs = [
        math.log(total / df) * (ENTITY_TERM_WEIGHT if lexeme in entity_lexemes else 1.0)
        for lexeme, df in terms
    ]

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ch.id::text,
                   ci.id::text,
                   -- IDF-weighted overlap, not `ts_rank_cd`.
                   --
                   -- `ts_rank_cd` has no IDF: every matched lexeme counts the
                   -- same. Measured consequence — asked 「智谱最近发布了什么」
                   -- the query ORs `智谱` (df 3) with the CJK bigrams `最近`,
                   -- `发布` and `什么`, which clear the 0.15 document-frequency
                   -- ceiling honestly and then outweigh the one term that
                   -- identifies the vendor. The channel returned 40 rows led by
                   -- 「自托管开源模型指南」 and 「推理工程大师课」, and the answer
                   -- said Zhipu had released nothing.
                   --
                   -- Summing ln(N/df) over the terms a chunk actually matches is
                   -- what BM25 would do about it, and it needs no new index: the
                   -- frequencies were already computed to build this query.
                   (SELECT COALESCE(sum(t.idf), 0)
                      FROM unnest(%s::text[], %s::float8[]) AS t(lexeme, idf)
                     WHERE ch.search_vector @@ to_tsquery('simple', t.lexeme)) AS rank,
                   COALESCE(ci.zh_title, ci.title),
                   s.name,
                   s.id,
                   s.source_tier
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
                lexemes,
                idfs,
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
                source_id=row[5] or "",
                source_tier=row[6] or "",
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

"""Parent-block expansion (M4 B5, ADR-0016).

Retrieval works on small chunks because precision needs them; generation needs
whatever makes the passage make sense. Those are different units, so the hit is
used to *find* the answer and its parent is what gets read.

The parent is not a fixed level. Measuring the corpus first (ADR-0016) ruled
that out:

    69.3%  of documents fit whole inside a 2000-token budget
    3519   tokens at the 90th percentile of a single heading section
    33.5%  of chunks carry no heading at all

So a fixed "section = parent" is oversized for the tail, redundant for the
majority, and **undefined for a third of the corpus**. Instead the ladder takes
the first granularity that fits:

    ① whole revision      ≤ budget
    ② its top-level heading section  ≤ budget
    ③ the hit ± one neighbour, hard capped

Nothing is materialised. `content_chunk` already stores `content_revision_id`,
`ordinal`, `heading_path` and `token_count`, so the parent is a query — no new
table, no re-embedding, and no second copy of the text to fall out of sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Starting value, to be calibrated against the golden set rather than kept as a
# constant (AHR-RAG-400 §5). Chosen because 69.3% of documents fit inside it.
PARENT_BUDGET_TOKENS = 2000

# Tier ③ never exceeds this, whatever the neighbours weigh.
HARD_CAP_TOKENS = 2600


@dataclass(frozen=True)
class ParentBlock:
    chunk_id: str
    revision_id: str
    tier: str  # "document" | "section" | "neighbours"
    text: str
    token_count: int
    chunk_ids: tuple[str, ...]


def choose_tier(
    *,
    document_tokens: int,
    section_tokens: int | None,
    budget: int = PARENT_BUDGET_TOKENS,
) -> str:
    """Which granularity the ladder lands on.

    Split out from the SQL so the decision itself is testable without a
    database — the branch that matters most, a chunk with no heading, is the
    one hardest to arrange as fixture data.
    """
    if document_tokens <= budget:
        return "document"
    if section_tokens is not None and section_tokens <= budget:
        return "section"
    return "neighbours"


def _rows_for(connection: Any, chunk_id: str) -> list[tuple[Any, ...]]:
    """Every sibling chunk of the hit's revision, with the hit marked."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH hit AS (
                SELECT content_revision_id, chunk_set_id, ordinal, heading_path
                  FROM content_chunk
                 WHERE id = %s::uuid
            )
            SELECT ch.id::text, ch.ordinal, ch.body_text, ch.token_count,
                   ch.heading_path, ch.content_revision_id::text,
                   hit.ordinal AS hit_ordinal,
                   COALESCE(hit.heading_path[1], '') AS hit_section
              FROM content_chunk ch
              JOIN hit ON hit.content_revision_id = ch.content_revision_id
                      AND hit.chunk_set_id = ch.chunk_set_id
             ORDER BY ch.ordinal
            """,
            (chunk_id,),
        )
        return list(cursor.fetchall())


def expand(
    connection: Any,
    chunk_id: str,
    *,
    budget: int = PARENT_BUDGET_TOKENS,
) -> ParentBlock | None:
    """Grow one hit into the largest coherent block that fits the budget."""
    rows = _rows_for(connection, chunk_id)
    if not rows:
        return None

    revision_id = rows[0][5]
    hit_ordinal = rows[0][6]
    hit_section = rows[0][7]

    document_tokens = sum(int(row[3] or 0) for row in rows)
    section_rows = (
        [row for row in rows if (row[4] or [""])[:1] == [hit_section]] if hit_section else []
    )
    section_tokens = sum(int(row[3] or 0) for row in section_rows) if section_rows else None

    tier = choose_tier(
        document_tokens=document_tokens, section_tokens=section_tokens, budget=budget
    )

    if tier == "document":
        selected = rows
    elif tier == "section":
        selected = section_rows
    else:
        # Neighbours, then trimmed to the cap from the outside in so the hit
        # itself is never the thing dropped.
        selected = [row for row in rows if abs(int(row[1]) - int(hit_ordinal)) <= 1]
        while len(selected) > 1 and sum(int(r[3] or 0) for r in selected) > HARD_CAP_TOKENS:
            drop = 0 if int(selected[0][1]) != int(hit_ordinal) else len(selected) - 1
            selected.pop(drop)

    return ParentBlock(
        chunk_id=chunk_id,
        revision_id=revision_id,
        tier=tier,
        text="\n\n".join(str(row[2] or "") for row in selected),
        token_count=sum(int(row[3] or 0) for row in selected),
        chunk_ids=tuple(str(row[0]) for row in selected),
    )


def tier_distribution(connection: Any, *, budget: int = PARENT_BUDGET_TOKENS) -> dict[str, int]:
    """How often each tier would fire across the whole corpus.

    ADR-0016's ratios came from a one-off query; this keeps them checkable as
    the corpus grows. If tier ① stops dominating — say long-form papers start
    arriving — the budget needs revisiting.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH doc AS (
                SELECT content_revision_id, sum(token_count) AS tokens
                  FROM content_chunk WHERE is_active GROUP BY 1
            ),
            sec AS (
                SELECT content_revision_id, COALESCE(heading_path[1], '') AS section,
                       sum(token_count) AS tokens
                  FROM content_chunk WHERE is_active GROUP BY 1, 2
            )
            SELECT
                count(*) FILTER (WHERE doc.tokens <= %s) AS document,
                count(*) FILTER (WHERE doc.tokens > %s AND sec.section <> ''
                                   AND sec.tokens <= %s) AS section,
                count(*) FILTER (WHERE doc.tokens > %s
                                   AND (sec.section = '' OR sec.tokens > %s)) AS neighbours
              FROM content_chunk ch
              JOIN doc ON doc.content_revision_id = ch.content_revision_id
              JOIN sec ON sec.content_revision_id = ch.content_revision_id
                      AND sec.section = COALESCE(ch.heading_path[1], '')
             WHERE ch.is_active
            """,
            (budget, budget, budget, budget, budget),
        )
        row = cursor.fetchone()

    return {"document": int(row[0]), "section": int(row[1]), "neighbours": int(row[2])}

"""Golden-set candidates, mined from what the system already got wrong.

The 90-question set was written by hand before launch, against a corpus frozen
at 2026-08-03. Two thirds of today's library postdates it, so the fixed set can
show that retrieval and citation *mechanics* have not regressed and cannot show
that answers over new material are right.

Refreshing it by inventing more questions would reproduce the same blind spot:
the questions someone thinks to write are the cases they already have in mind.
Real traffic does not have that bias, and it comes with the system's own
verdict attached — a citation the cross-encoder scored below the support
threshold is a passage the pipeline itself judged too weak for the sentence it
was attached to. Those are the hard cases, already labelled, for free.

**What this produces is a shortlist, not a golden set.** Every candidate still
needs a human to mark which documents are genuinely relevant. That step is not
automatable here: asking the model to annotate the set it will be graded on
lets it write the exam and sit it.

Four bands, most-diagnostic first:

* ``weak_support`` — the answer shipped, but a citation failed entailment.
* ``refused`` — the system declined. Correct refusals become abstention
  questions; incorrect ones become the over-refusal cases the gate watches.
* ``uncited`` — answered with no citation at all: shaped like a normal answer,
  carrying nothing checkable.
* ``new_source`` — questions whose evidence came from a source the frozen
  corpus never contained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Matches `support.SUPPORT_THRESHOLD`; imported at call time so the two cannot
#: drift into disagreeing about what "unsupported" means.
from ahr.rag.support import SUPPORT_THRESHOLD

BANDS = ("weak_support", "refused", "uncited", "new_source")


@dataclass
class Candidate:
    """One real question worth annotating, with why it was picked."""

    query_id: str
    question: str
    band: str
    asked_at: str | None
    #: Lowest support score among the answer's citations. None when unscored.
    worst_support: float | None
    citations: int
    #: Documents the pipeline actually used, as a starting point for the
    #: annotator — deliberately *not* called `relevant_items`. Whether they are
    #: relevant is the judgement being asked for, and pre-filling that field
    #: would turn review into agreement.
    retrieved: list[dict[str, str]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "question": self.question,
            "band": self.band,
            "asked_at": self.asked_at,
            "worst_support": self.worst_support,
            "citations": self.citations,
            "sources": self.sources,
            "retrieved": self.retrieved,
        }


def _rows(connection: Any, sql: str, params: Any) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


#: One question can qualify for several bands. It is listed under the first one
#: it matches, in the order of `BANDS`, so the shortlist has no duplicates and
#: the strongest reason wins.
_SELECT = """
    SELECT q.id::text, q.question, q.created_at,
           min(c.support_score) AS worst,
           count(c.*) AS citations,
           array_remove(array_agg(DISTINCT s.name), NULL) AS sources,
           bool_or(COALESCE(ci.published_at, ci.observed_at) > %(cutoff)s) AS uses_new
      FROM rag_query q
      LEFT JOIN rag_citation c ON c.rag_query_id = q.id
      LEFT JOIN content_chunk ch ON ch.id = c.content_chunk_id
      LEFT JOIN content_revision cr ON cr.id = ch.content_revision_id
      LEFT JOIN content_item ci ON ci.id = cr.content_item_id
      LEFT JOIN source s ON s.id = ci.source_id
     WHERE q.created_at >= now() - make_interval(days => %(days)s)
     GROUP BY q.id, q.question, q.created_at, q.status
"""


def _band(status_refused: bool, citations: int, worst: float | None, uses_new: bool) -> str | None:
    if worst is not None and worst < SUPPORT_THRESHOLD:
        return "weak_support"
    if status_refused:
        return "refused"
    if citations == 0:
        return "uncited"
    if uses_new:
        return "new_source"
    return None


def mine(connection: Any, *, cutoff: str, days: int = 90, limit: int = 60) -> dict[str, Any]:
    """Rank real questions by how much annotating them would teach.

    `cutoff` is the frozen corpus boundary from the published snapshot, so
    `new_source` means "evidence the golden set structurally cannot contain"
    rather than "recent".
    """
    refused_ids = {
        row[0]
        for row in _rows(
            connection,
            "SELECT id::text FROM rag_query WHERE status = 'REFUSED'"
            " AND created_at >= now() - make_interval(days => %s)",
            (days,),
        )
    }

    seen: set[str] = set()
    picked: list[Candidate] = []
    rows = _rows(
        connection,
        _SELECT + " ORDER BY min(c.support_score) NULLS LAST",
        {"cutoff": cutoff, "days": days},
    )
    for query_id, question, asked, worst, citations, sources, uses_new in rows:
        band = _band(query_id in refused_ids, int(citations or 0), worst, bool(uses_new))
        if band is None or question in seen:
            continue
        seen.add(question)
        picked.append(
            Candidate(
                query_id=query_id,
                question=question,
                band=band,
                asked_at=asked.isoformat() if asked else None,
                worst_support=round(float(worst), 4) if worst is not None else None,
                citations=int(citations or 0),
                sources=sorted(sources or []),
            )
        )

    order = {band: index for index, band in enumerate(BANDS)}
    picked.sort(
        key=lambda c: (order[c.band], c.worst_support if c.worst_support is not None else 1)
    )
    shortlist = picked[:limit]

    return {
        "cutoff": cutoff,
        "days": days,
        "support_threshold": SUPPORT_THRESHOLD,
        "distinct_questions": len(seen),
        "by_band": {band: sum(1 for c in picked if c.band == band) for band in BANDS},
        "candidates": [c.as_dict() for c in shortlist],
        "note": (
            "候选清单，不是黄金集。每一条仍需人工标注 relevant_items；"
            "retrieved 只是流水线当时用过的文档，是否相关正是要人判断的事。"
        ),
    }

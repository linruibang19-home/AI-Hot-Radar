"""Is the golden set still describing this corpus?

The 90 questions were annotated against the corpus as it stood on 2026-08-03.
That corpus has since grown from about 1125 items to 1578, and ingestion adds
more every two minutes. An evaluation set is only a measuring instrument for as
long as its annotations still hold, and nothing was checking that.

Three ways it rots, in increasing order of how quietly it happens:

1. **An annotated item disappears.** Re-chunking, a dedup merge or a deletion
   can leave `relevant_items` pointing at a row that is no longer there. Recall
   is then computed against a target that cannot be retrieved, so the score
   drops for a reason that has nothing to do with retrieval.

2. **An annotated item stops being retrievable.** The row survives but its
   current revision has no embedded chunk — the failure this project has
   already shipped once, where every counter looked healthy and the content was
   invisible to search (§3.12).

3. **New content arrives that *should* have been annotated.** This is the one
   that cannot be detected automatically and is therefore only *flagged*: a
   question asked on 08-03 about "本周的动态" has a different correct answer
   today, and no amount of checking ids will notice. What is reported instead
   is how much corpus has arrived since the annotation date, which is the cue
   for a human to re-check rather than an answer.

This is a report, not a gate. It has no opinion about whether the numbers are
still valid — it says what changed underneath them.
"""

from __future__ import annotations

from typing import Any

from ahr.rag.eval.golden import GoldenSet

# Above this, the annotations describe a meaningfully different corpus and the
# set is worth re-reading. Not a threshold anything enforces; a prompt.
GROWTH_REVIEW_THRESHOLD = 0.25


def check(connection: Any, golden: GoldenSet) -> dict[str, Any]:
    """Compare the golden set's annotations against the corpus as it is now."""
    annotated = sorted(golden.item_ids)
    asked_at = [q.asked_at for q in golden.questions if q.asked_at is not None]
    oldest = min(asked_at) if asked_at else None

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id::text FROM content_item WHERE id::text = ANY(%s)",
            (annotated,),
        )
        present = {row[0] for row in cursor.fetchall()}

        # Retrievable means "has an embedded chunk on its *current* revision".
        # Checking the item alone would miss the case where re-chunking left the
        # chunks attached to a superseded revision that nothing joins to.
        cursor.execute(
            """
            SELECT ci.id::text
              FROM content_item ci
              JOIN content_revision cr ON cr.id = ci.current_revision_id
              JOIN content_chunk ch ON ch.content_revision_id = cr.id
             WHERE ci.id::text = ANY(%s) AND ch.embedding IS NOT NULL
             GROUP BY ci.id
            """,
            (annotated,),
        )
        retrievable = {row[0] for row in cursor.fetchall()}

        cursor.execute("SELECT count(*) FROM content_item")
        corpus_now = int((cursor.fetchone() or (0,))[0])

        arrived_since = 0
        if oldest is not None:
            cursor.execute(
                "SELECT count(*) FROM content_item WHERE COALESCE(published_at, observed_at) > %s",
                (oldest,),
            )
            arrived_since = int((cursor.fetchone() or (0,))[0])

    missing = [item for item in annotated if item not in present]
    unretrievable = [item for item in annotated if item in present and item not in retrievable]

    # Which questions the damage lands on. A count of broken ids says how bad it
    # is; a list of question ids says which measurements to stop quoting.
    affected = sorted(
        q.id
        for q in golden.questions
        if q.relevant_ids and any(i in set(missing) | set(unretrievable) for i in q.relevant_ids)
    )

    growth = arrived_since / max(corpus_now - arrived_since, 1)
    return {
        "annotatedItems": len(annotated),
        "missing": missing,
        "unretrievable": unretrievable,
        "affectedQuestions": affected,
        "annotatedAt": oldest.isoformat() if oldest else None,
        "corpusNow": corpus_now,
        "arrivedSinceAnnotation": arrived_since,
        "corpusGrowth": round(growth, 4),
        # The one that needs a person. Time-relative questions ("本周有什么动态")
        # have a different correct answer every day, and no id check sees that.
        "reviewRecommended": bool(missing or unretrievable or growth > GROWTH_REVIEW_THRESHOLD),
    }

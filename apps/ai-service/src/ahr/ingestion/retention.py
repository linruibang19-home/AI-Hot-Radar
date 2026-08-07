"""Bounding the tables that only ever grow.

`outbox_event` is the one that matters, and it deserves an honest description
rather than the one in ADR-007. The write path is real: the row commits in the
same transaction as the content it describes, which is the whole point of the
outbox pattern. **The read path does not exist.** There is no consumer, and
`published_at` is NULL on every row ever written.

That is not a correctness problem — downstream processing polls
`content_item.enrichment_state`, and since the zero-chunk fix the code that
makes an item stale is also the code that marks it PENDING. It is a growth
problem: 1562 rows in the first week, nothing removing them, forever.

Two options were open: stop writing until a consumer exists, or keep writing
and bound the table. Keeping the write is the better trade — it is already
implemented and tested, it costs one insert per document, and it preserves the
transactional property that would be tedious to reintroduce later. What it
needs is a ceiling.

**When a consumer does land, this rule must change.** Deleting unpublished
rows is only acceptable while nobody would have read them; after that, the
predicate has to become `published_at IS NOT NULL`, or the pruner will start
silently discarding work. The guard below makes that a failure rather than a
surprise: as soon as anything is published, the unpublished rows stop being
eligible for deletion.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Long enough to debug last week's ingestion, short enough to keep the table
# small. Nothing reads these rows, so this is a debugging window, not a
# delivery guarantee.
OUTBOX_RETENTION_DAYS = 14


def prune_outbox(connection: Any, *, retention_days: int = OUTBOX_RETENTION_DAYS) -> int:
    """Delete outbox rows older than the retention window. Returns the count.

    Deletes only rows that no consumer could have been waiting on:

    * if nothing has ever been published, there is no consumer and old rows are
      debris;
    * once anything has been published, a consumer exists, and only rows it has
      already handled may be removed.

    The second branch is not speculative tidiness — it is what stops this
    function from quietly eating a backlog on the day someone wires up a reader.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM outbox_event WHERE published_at IS NOT NULL")
        row = cursor.fetchone()
        has_consumer = bool(row and row[0])

        if has_consumer:
            cursor.execute(
                """
                DELETE FROM outbox_event
                 WHERE published_at IS NOT NULL
                   AND published_at < now() - make_interval(days => %s)
                """,
                (retention_days,),
            )
        else:
            cursor.execute(
                """
                DELETE FROM outbox_event
                 WHERE created_at < now() - make_interval(days => %s)
                """,
                (retention_days,),
            )
        deleted = cursor.rowcount or 0
    connection.commit()

    if deleted:
        logger.info(
            "pruned %s outbox rows older than %s days (consumer=%s)",
            deleted,
            retention_days,
            has_consumer,
        )
    return int(deleted)

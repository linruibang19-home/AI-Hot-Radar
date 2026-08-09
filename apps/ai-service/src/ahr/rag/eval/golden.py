"""Load and validate the RAG golden set.

Relevance is annotated against `content_item`, not `content_chunk`. Chunk ids
are destroyed by any change to the chunker, and AHR-RAG-400 §14 requires a
regression run precisely when the chunker changes — a chunk-keyed golden set
would expire at the exact moment it is needed. This corpus has already been
re-chunked once.

The cost is coarser granularity: retrieving the wrong passage of the right
document still counts as a hit. That is accepted deliberately. Recall answers
"did the relevant document reach the candidate set"; passage-level precision is
measured separately by the citation metrics during generation.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from ahr.rag.planner import QUERY_TYPES

CATEGORIES = (
    "recent_updates",
    "timeline",
    "comparison",
    "fact_check",
    "explainer",
    "abstention",
)

# AHR-RAG-400 §14 requires at least 15 questions per category.
MIN_PER_CATEGORY = 15

VALID_GRADES = (1, 2)


class GoldenSetError(ValueError):
    """The golden set is malformed. Never silently tolerated: a broken golden
    set produces plausible-looking metrics computed against the wrong truth."""


@dataclass(frozen=True)
class RelevantItem:
    item_id: str
    grade: int


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    category: str
    question: str
    asked_at: datetime
    answerable: bool
    relevant_items: tuple[RelevantItem, ...] = ()
    must_contain: tuple[str, ...] = ()
    must_not_claim: tuple[str, ...] = ()
    # The false thing an answer must not assert, written as a sentence rather
    # than a keyword. `must_not_claim` is substring matching and cannot tell a
    # denial from an assertion; this is what the abstention judge is given.
    presupposition: str | None = None
    # Planner ground truth (`AHR-QSO-700` §8 entity/time planner accuracy,
    # `AHR-RAG-400` §14 entity/time/type). All optional: a question with none of
    # them is skipped by the planner run rather than counted as a failure, and
    # the run reports how much of the set is annotated so a high score over
    # three questions cannot be mistaken for a high score over ninety.
    #
    # **Annotate from the question, not from the planner's rules.** Deriving the
    # expected value by applying §3's defaults measures nothing — it asks the
    # implementation to agree with itself. What is wanted is what a reader
    # meant, which is why this cannot be generated.
    expected_query_type: str | None = None
    # `None` means "not annotated"; an explicit `no_window` means "the planner
    # should resolve no time range at all", which is a real expectation for
    # explainer questions and the opposite of missing.
    expected_time: tuple[date, date] | str | None = None
    expected_entities: tuple[str, ...] = ()
    probe: str | None = None
    notes: str | None = None

    @property
    def has_planner_annotation(self) -> bool:
        return bool(self.expected_query_type or self.expected_time or self.expected_entities)

    @property
    def relevant_ids(self) -> frozenset[str]:
        return frozenset(item.item_id for item in self.relevant_items)

    def grade_of(self, item_id: str) -> int:
        for item in self.relevant_items:
            if item.item_id == item_id:
                return item.grade
        return 0


@dataclass(frozen=True)
class GoldenSet:
    questions: tuple[GoldenQuestion, ...]
    source_files: tuple[str, ...] = field(default=())

    def __len__(self) -> int:
        return len(self.questions)

    def by_category(self, category: str) -> tuple[GoldenQuestion, ...]:
        return tuple(q for q in self.questions if q.category == category)

    @property
    def answerable(self) -> tuple[GoldenQuestion, ...]:
        return tuple(q for q in self.questions if q.answerable)

    @property
    def item_ids(self) -> frozenset[str]:
        return frozenset(item_id for q in self.questions for item_id in q.relevant_ids)


def _parse_question(raw: dict[str, Any], category: str, path: Path) -> GoldenQuestion:
    def fail(message: str) -> GoldenSetError:
        return GoldenSetError(f"{path.name}: {raw.get('id', '<no id>')}: {message}")

    for required in ("id", "question", "asked_at", "answerable"):
        if required not in raw:
            raise fail(f"missing required field '{required}'")

    asked_at = raw["asked_at"]
    if isinstance(asked_at, str):
        asked_at = datetime.fromisoformat(asked_at)
    if not isinstance(asked_at, datetime):
        raise fail("asked_at must be a timestamp")
    if asked_at.tzinfo is None:
        # A naive timestamp would be interpreted differently depending on where
        # the evaluation runs, which is exactly the class of bug that made the
        # whole site render UTC. Time-sensitive questions must pin an offset.
        raise fail("asked_at must carry a timezone offset")

    answerable = bool(raw["answerable"])
    relevant: list[RelevantItem] = []
    for entry in raw.get("relevant_items") or ():
        if not isinstance(entry, dict) or "id" not in entry:
            raise fail("relevant_items entries need an 'id'")
        grade = int(entry.get("grade", 2))
        if grade not in VALID_GRADES:
            raise fail(f"grade must be one of {VALID_GRADES}, got {grade}")
        relevant.append(RelevantItem(item_id=str(entry["id"]), grade=grade))

    if not answerable and relevant:
        raise fail("an unanswerable question must not list relevant items")
    if answerable and not relevant:
        raise fail("an answerable question needs at least one relevant item")

    ids = [item.item_id for item in relevant]
    duplicates = [item_id for item_id, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise fail(f"duplicate relevant item ids: {duplicates}")

    expected_query_type = raw.get("expected_query_type")
    if expected_query_type is not None and expected_query_type not in QUERY_TYPES:
        raise fail(f"expected_query_type must be one of {QUERY_TYPES}, got {expected_query_type!r}")

    expected_time = _parse_expected_time(raw.get("expected_time"), fail)

    return GoldenQuestion(
        id=str(raw["id"]),
        category=category,
        question=str(raw["question"]),
        asked_at=asked_at,
        answerable=answerable,
        relevant_items=tuple(relevant),
        must_contain=tuple(str(v) for v in raw.get("must_contain") or ()),
        must_not_claim=tuple(str(v) for v in raw.get("must_not_claim") or ()),
        presupposition=raw.get("presupposition"),
        expected_query_type=expected_query_type,
        expected_time=expected_time,
        expected_entities=tuple(str(v) for v in raw.get("expected_entities") or ()),
        probe=raw.get("probe"),
        notes=raw.get("notes"),
    )


NO_WINDOW = "no_window"


def _parse_expected_time(
    raw: Any, fail: Callable[[str], GoldenSetError]
) -> tuple[date, date] | str | None:
    """Read `expected_time`: absent, `no_window`, or a `{from, to}` date pair.

    Dates rather than timestamps, and absolute rather than a phrase like
    "last week". `asked_at` is pinned per question, so the expected window is a
    fixed pair of days that a human can compute once and check by eye — whereas
    a phrase would have to be interpreted by the same code being measured.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw != NO_WINDOW:
            raise fail(f"expected_time must be a mapping or {NO_WINDOW!r}, got {raw!r}")
        return NO_WINDOW
    if not isinstance(raw, dict) or "from" not in raw or "to" not in raw:
        raise fail("expected_time needs 'from' and 'to', or the string 'no_window'")

    bounds: list[date] = []
    for field_name in ("from", "to"):
        value = raw[field_name]
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, str):
            value = date.fromisoformat(value)
        if not isinstance(value, date):
            raise fail(f"expected_time.{field_name} must be a date")
        bounds.append(value)

    if bounds[1] < bounds[0]:
        raise fail("expected_time.to is before expected_time.from")
    return (bounds[0], bounds[1])


def load_golden_set(directory: Path, *, require_full: bool = True) -> GoldenSet:
    """Read every `*.yaml` under `directory` into one validated set.

    `require_full` is off in unit tests that exercise a fixture of a few
    questions; the real run keeps it on so an accidentally truncated file fails
    loudly instead of quietly reporting metrics over 40 questions.
    """
    files = sorted(p for p in directory.glob("*.yaml"))
    if not files:
        raise GoldenSetError(f"no golden set files under {directory}")

    questions: list[GoldenQuestion] = []
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise GoldenSetError(f"{path.name}: expected a mapping at the top level")

        category = payload.get("category")
        if category not in CATEGORIES:
            raise GoldenSetError(f"{path.name}: unknown category {category!r}")

        for raw in payload.get("questions") or ():
            questions.append(_parse_question(raw, category, path))

    ids = [q.id for q in questions]
    duplicated = sorted(qid for qid, count in Counter(ids).items() if count > 1)
    if duplicated:
        raise GoldenSetError(f"duplicate question ids: {duplicated}")

    if require_full:
        for category in CATEGORIES:
            count = sum(1 for q in questions if q.category == category)
            if count < MIN_PER_CATEGORY:
                raise GoldenSetError(
                    f"category {category} has {count} questions, "
                    f"AHR-RAG-400 §14 requires at least {MIN_PER_CATEGORY}"
                )

    return GoldenSet(
        questions=tuple(questions),
        source_files=tuple(p.name for p in files),
    )


def verify_items_exist(connection: Any, golden: GoldenSet) -> list[str]:
    """Annotated item ids that are missing, or are marked as duplicates.

    Three ways an annotation can point at something unreachable, all of which
    look like a retrieval failure and none of which are:

    * the row is gone;
    * the deduplicator pointed `duplicate_of_id` at a surviving copy, and only
      that copy is served;
    * **the current revision has no chunks**, so nothing about the item is in
      the index at all.

    The last one was missed by an earlier version of this check and cost a real
    diagnosis: RAG-GOLD-049's answer confidently named a quantum-computer
    calibration tool because the document that actually answered it had been
    re-ingested into a fresh revision that was never chunked. Retrieval could
    not have found it, and the evaluation had no way to say so.
    """
    wanted = sorted(golden.item_ids)
    if not wanted:
        return []

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ci.id::text
              FROM content_item ci
             WHERE ci.id = ANY(%s::uuid[])
               AND ci.duplicate_of_id IS NULL
               AND ci.current_revision_id IS NOT NULL
               AND EXISTS (SELECT 1 FROM content_chunk ch
                            WHERE ch.content_revision_id = ci.current_revision_id)
            """,
            (wanted,),
        )
        usable = {row[0] for row in cursor.fetchall()}

    return [item_id for item_id in wanted if item_id not in usable]


def describe_corpus_snapshot(connection: Any, golden: GoldenSet) -> dict[str, Any]:
    """How much of the corpus each run ignores, and why.

    Retrieval is clamped to the corpus as it stood at each question's
    `asked_at` (see `snapshot_window`), so items ingested afterwards are
    invisible by design — that is what keeps the annotations valid and a rerun
    reproducible.

    This used to be a blocking check requiring `asked_at` to stay ahead of the
    newest item. That was the wrong shape: it failed again with every hour of
    ingestion, and it discarded the reproducibility it was meant to protect.
    What remains is the number itself, recorded in the report so the reader
    knows the run covered 918 items rather than today's 1200.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT max(COALESCE(published_at, observed_at))
              FROM content_item
             WHERE duplicate_of_id IS NULL
            """
        )
        row = cursor.fetchone()

    newest = row[0] if row else None
    cutoff = max((q.asked_at for q in golden.questions), default=None)
    if newest is None or cutoff is None:
        return {}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FILTER (WHERE COALESCE(published_at, observed_at) <= %s),
                   count(*)
              FROM content_item
             WHERE duplicate_of_id IS NULL
            """,
            (cutoff,),
        )
        in_snapshot, total = cursor.fetchone()

    return {
        "snapshot_cutoff": cutoff.isoformat(),
        "newest_item": newest.isoformat(),
        "items_in_snapshot": int(in_snapshot),
        "items_total": int(total),
        "items_ignored": int(total) - int(in_snapshot),
    }

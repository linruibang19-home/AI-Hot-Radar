"""Planner accuracy: the one §8 gate that has never had a number.

`AHR-QSO-700` §8 requires `entity/time planner accuracy >= 0.90` and
`AHR-RAG-400` §14 lists entity/time/type. Nothing measured any of them, so the
gate was not failing — it was **unjudgeable**, which is worse, because a gate
nobody can evaluate reads as a gate nobody has to.

The planner is not a small component to leave unmeasured. `query_type` and
`freshness_required` decide three things downstream: whether the time window
filters the dense and sparse channels at all, which row of the `source_fit`
affinity table applies, and whether `temporal_fit` runs. **A misclassification
is silent** — nothing errors, the system just quietly searches the wrong period
or prefers the wrong kind of source.

Scoring is over annotated questions only, and the coverage is reported next to
the score. A planner accuracy of 1.00 over three annotated questions is not a
passing gate, and the report has to make that impossible to misread.

Requires no model call and no database: the planner is pure functions over the
question and `asked_at`, so this run is free and can go in CI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ahr.rag.eval.golden import NO_WINDOW, GoldenQuestion, GoldenSet
from ahr.rag.planner import DISPLAY_TIMEZONE, plan


@dataclass
class PlannerResult:
    question_id: str
    category: str
    # None where the question carries no annotation for that field: "not
    # measured" must never collapse into "wrong".
    query_type_correct: bool | None = None
    time_correct: bool | None = None
    entities_correct: bool | None = None
    predicted_query_type: str | None = None
    predicted_time: str | None = None
    expected_time: str | None = None
    notes: list[str] = field(default_factory=list)


def _describe(window: tuple[Any, Any] | None) -> str:
    if window is None:
        return NO_WINDOW
    return f"{window[0].isoformat()}..{window[1].isoformat()}"


def score_question(question: GoldenQuestion) -> PlannerResult:
    """Compare one planned query against what the question was annotated to mean."""
    retrieval_plan = plan(question.question, asked_at=question.asked_at)
    window = retrieval_plan.time_range

    result = PlannerResult(
        question_id=question.id,
        category=question.category,
        predicted_query_type=retrieval_plan.query_type,
    )

    if question.expected_query_type is not None:
        result.query_type_correct = retrieval_plan.query_type == question.expected_query_type
        if not result.query_type_correct:
            result.notes.append(
                f"分类：期望 {question.expected_query_type}，实际 {retrieval_plan.query_type}"
            )

    if question.expected_time is not None:
        # Compared as local dates, not instants. The annotation says which days
        # the reader meant; a half-open range that ends at midnight would fail
        # an instant-level comparison for a reason that has nothing to do with
        # the planner being right.
        if window is None:
            predicted = None
        else:
            start = window.start.astimezone(DISPLAY_TIMEZONE).date()
            # The window is half-open, so when `end` lands exactly on midnight
            # the last day it actually covers is the one before. Annotating
            # "上周" as 07-27..08-02 and having it read as ..08-03 would fail a
            # correct planner for an off-by-one in the comparison, not in it.
            local_end = window.end.astimezone(DISPLAY_TIMEZONE)
            midnight = (local_end.hour, local_end.minute, local_end.second) == (0, 0, 0)
            end = (local_end - timedelta(days=1)).date() if midnight else local_end.date()
            predicted = (start, end)

        result.predicted_time = _describe(predicted)
        result.expected_time = (
            NO_WINDOW if question.expected_time == NO_WINDOW else _describe(question.expected_time)  # type: ignore[arg-type]
        )

        if question.expected_time == NO_WINDOW:
            result.time_correct = predicted is None
        else:
            result.time_correct = predicted == question.expected_time

        if not result.time_correct:
            result.notes.append(
                f"时间窗：期望 {result.expected_time}，实际 {result.predicted_time}"
            )

    if question.expected_entities:
        # Substring match against the question, which is what
        # `resolve_query_entities` does against the corpus vocabulary — checked
        # here without a database so this run stays free. It answers "is the
        # entity nameable from the question", not "is it in the entity table";
        # the latter is a corpus property, not a planner one.
        lowered = question.question.lower()
        missing = [name for name in question.expected_entities if name.lower() not in lowered]
        result.entities_correct = not missing
        if missing:
            result.notes.append(f"实体：问句中找不到 {', '.join(missing)}")

    return result


def _rate(values: list[bool | None]) -> float | None:
    scored = [v for v in values if v is not None]
    if not scored:
        return None
    return round(sum(1 for v in scored if v) / len(scored), 4)


def summarise(results: list[PlannerResult], total_questions: int) -> dict[str, Any]:
    annotated = [
        r
        for r in results
        if r.query_type_correct is not None
        or r.time_correct is not None
        or r.entities_correct is not None
    ]

    overall: dict[str, Any] = {
        "questions": total_questions,
        # Reported next to every score, deliberately. `AHR-QSO-700` §8 asks for
        # >= 0.90; over four annotated questions that number means nothing, and
        # a reader must not be able to see the score without the denominator.
        "annotated": len(annotated),
        "annotation_coverage": round(len(annotated) / total_questions, 4)
        if total_questions
        else None,
        "query_type_accuracy": _rate([r.query_type_correct for r in results]),
        "time_accuracy": _rate([r.time_correct for r in results]),
        "entity_accuracy": _rate([r.entities_correct for r in results]),
    }

    scored_type = [r for r in results if r.query_type_correct is not None]
    scored_time = [r for r in results if r.time_correct is not None]
    overall["query_type_scored"] = len(scored_type)
    overall["time_scored"] = len(scored_time)

    by_category: dict[str, Any] = {}
    for category in sorted({r.category for r in annotated}):
        rows = [r for r in annotated if r.category == category]
        by_category[category] = {
            "annotated": len(rows),
            "query_type_accuracy": _rate([r.query_type_correct for r in rows]),
            "time_accuracy": _rate([r.time_correct for r in rows]),
        }

    return {"overall": overall, "by_category": by_category}


def run_planner_eval(golden: GoldenSet, *, run_id: str | None = None) -> dict[str, Any]:
    """Score the planner over whatever part of the golden set is annotated."""
    results = [score_question(q) for q in golden.questions]
    summary = summarise(results, len(golden.questions))

    mistakes = [asdict(r) for r in results if r.notes]
    return {
        "run_id": run_id or datetime.now(UTC).strftime("PLAN-%Y%m%dT%H%M%SZ"),
        "config": {
            "variant": "planner",
            "golden_files": list(golden.source_files),
            "golden_questions": len(golden),
        },
        "summary": summary,
        # Every disagreement, in full. A rate says the planner is wrong 8% of
        # the time; only the rows say which questions and how, and that is what
        # decides whether the fix is a regex or a rethink.
        "mistakes": mistakes,
        "questions": [asdict(r) for r in results],
    }

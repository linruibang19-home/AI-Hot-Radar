"""Auditable sampling and evaluation for topic-map relations.

The production projection is deterministic, but deterministic does not mean
correct.  This module freezes stratified candidates against a corpus snapshot
and evaluates *human* labels.  It deliberately refuses to turn pending labels
into a quality score: the classifier cannot grade itself.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import yaml

Dimension = Literal["vendor", "topic"]
VendorPrediction = Literal["primary", "related", "mention", "unmatched"]
TopicPrediction = Literal["public", "suppressed", "unmatched"]

VENDOR_PREDICTIONS = frozenset({"primary", "related", "mention", "unmatched"})
VENDOR_GOLD = frozenset({"primary", "related", "mention", "unrelated"})
TOPIC_PREDICTIONS = frozenset({"public", "suppressed", "unmatched"})
TOPIC_GOLD = frozenset({"relevant", "unrelated"})


class TopicQualityError(ValueError):
    """The relation-quality dataset is malformed or not ready to score."""


@dataclass(frozen=True)
class RelationSample:
    id: str
    dimension: Dimension
    target_slug: str
    predicted_label: str
    population_size: int
    content_item_id: str
    current_revision_id: str
    content_sha256: str
    canonical_url: str
    title: str
    source_name: str
    original_excerpt: str
    gold_label: str | None
    reviewer: str | None
    reviewed_at: str | None

    @property
    def stratum(self) -> tuple[str, str, str]:
        return self.dimension, self.target_slug, self.predicted_label


@dataclass(frozen=True)
class RelationDataset:
    schema_version: int
    dataset_id: str
    seed: str
    per_stratum: int
    strata: tuple[tuple[Dimension, str, str, int], ...]
    samples: tuple[RelationSample, ...]
    document: dict[str, Any]


def _required_text(raw: dict[str, Any], field: str, *, sample_id: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TopicQualityError(f"{sample_id}: {field} must be non-empty text")
    return value.strip()


def _optional_text(raw: dict[str, Any], field: str, *, sample_id: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TopicQualityError(f"{sample_id}: {field} must be null or non-empty text")
    return value.strip()


def _parse_sample(raw: object, index: int) -> RelationSample:
    if not isinstance(raw, dict):
        raise TopicQualityError(f"samples[{index}] must be an object")
    payload = cast(dict[str, Any], raw)
    sample_id = _required_text(payload, "id", sample_id=f"samples[{index}]")
    dimension = _required_text(payload, "dimension", sample_id=sample_id)
    if dimension not in {"vendor", "topic"}:
        raise TopicQualityError(f"{sample_id}: unknown dimension {dimension!r}")

    predicted = _required_text(payload, "predicted_label", sample_id=sample_id)
    predictions = VENDOR_PREDICTIONS if dimension == "vendor" else TOPIC_PREDICTIONS
    if predicted not in predictions:
        raise TopicQualityError(
            f"{sample_id}: predicted_label {predicted!r} is invalid for {dimension}"
        )

    gold = _optional_text(payload, "gold_label", sample_id=sample_id)
    allowed_gold = VENDOR_GOLD if dimension == "vendor" else TOPIC_GOLD
    if gold is not None and gold not in allowed_gold:
        raise TopicQualityError(f"{sample_id}: gold_label {gold!r} is invalid for {dimension}")

    population = payload.get("population_size")
    if not isinstance(population, int) or isinstance(population, bool) or population < 1:
        raise TopicQualityError(f"{sample_id}: population_size must be a positive integer")

    reviewer = _optional_text(payload, "reviewer", sample_id=sample_id)
    reviewed_at = _optional_text(payload, "reviewed_at", sample_id=sample_id)
    if gold is None and (reviewer is not None or reviewed_at is not None):
        raise TopicQualityError(f"{sample_id}: pending samples cannot carry review metadata")
    if gold is not None and (reviewer is None or reviewed_at is None):
        raise TopicQualityError(f"{sample_id}: reviewed samples need reviewer and reviewed_at")
    if reviewed_at is not None:
        try:
            parsed_reviewed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TopicQualityError(f"{sample_id}: reviewed_at is not ISO-8601") from exc
        if parsed_reviewed_at.tzinfo is None:
            raise TopicQualityError(f"{sample_id}: reviewed_at must include a timezone")

    return RelationSample(
        id=sample_id,
        dimension=cast(Dimension, dimension),
        target_slug=_required_text(payload, "target_slug", sample_id=sample_id),
        predicted_label=predicted,
        population_size=population,
        content_item_id=_required_text(payload, "content_item_id", sample_id=sample_id),
        current_revision_id=_required_text(payload, "current_revision_id", sample_id=sample_id),
        content_sha256=_required_text(payload, "content_sha256", sample_id=sample_id),
        canonical_url=_required_text(payload, "canonical_url", sample_id=sample_id),
        title=_required_text(payload, "title", sample_id=sample_id),
        source_name=_required_text(payload, "source_name", sample_id=sample_id),
        original_excerpt=_required_text(payload, "original_excerpt", sample_id=sample_id),
        gold_label=gold,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
    )


def load_dataset(path: str | Path) -> RelationDataset:
    """Load and strictly validate a frozen relation-quality dataset."""
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TopicQualityError(f"{source}: root must be an object")
    document = cast(dict[str, Any], payload)

    schema_version = document.get("schema_version")
    if schema_version != 1:
        raise TopicQualityError(f"{source}: schema_version must be 1")
    dataset_id = document.get("dataset_id")
    seed = document.get("seed")
    per_stratum = document.get("per_stratum")
    raw_strata = document.get("strata")
    raw_samples = document.get("samples")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise TopicQualityError(f"{source}: dataset_id must be non-empty text")
    if not isinstance(seed, str) or not seed.strip():
        raise TopicQualityError(f"{source}: seed must be non-empty text")
    if not isinstance(per_stratum, int) or isinstance(per_stratum, bool) or per_stratum < 1:
        raise TopicQualityError(f"{source}: per_stratum must be a positive integer")
    if not isinstance(raw_strata, list) or not raw_strata:
        raise TopicQualityError(f"{source}: strata must be a non-empty list")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise TopicQualityError(f"{source}: samples must be a non-empty list")

    samples = tuple(_parse_sample(raw, index) for index, raw in enumerate(raw_samples))
    strata: list[tuple[Dimension, str, str, int]] = []
    stratum_populations: dict[tuple[str, str, str], int] = {}
    for index, raw in enumerate(raw_strata):
        if not isinstance(raw, dict):
            raise TopicQualityError(f"strata[{index}] must be an object")
        item = cast(dict[str, Any], raw)
        marker = f"strata[{index}]"
        dimension = _required_text(item, "dimension", sample_id=marker)
        target = _required_text(item, "target_slug", sample_id=marker)
        prediction = _required_text(item, "predicted_label", sample_id=marker)
        if dimension not in {"vendor", "topic"}:
            raise TopicQualityError(f"{marker}: unknown dimension {dimension!r}")
        allowed_predictions = VENDOR_PREDICTIONS if dimension == "vendor" else TOPIC_PREDICTIONS
        if prediction not in allowed_predictions:
            raise TopicQualityError(f"{marker}: invalid predicted_label {prediction!r}")
        population = item.get("population_size")
        if not isinstance(population, int) or isinstance(population, bool) or population < 0:
            raise TopicQualityError(f"{marker}: population_size must be a non-negative integer")
        key = (dimension, target, prediction)
        if key in stratum_populations:
            raise TopicQualityError(f"duplicate stratum: {'/'.join(key)}")
        stratum_populations[key] = population
        strata.append((cast(Dimension, dimension), target, prediction, population))

    target_predictions: dict[tuple[str, str], set[str]] = defaultdict(set)
    for dimension, target, prediction, _population in strata:
        target_predictions[(dimension, target)].add(prediction)
    for (dimension, target), actual_predictions in target_predictions.items():
        expected_predictions = set(
            VENDOR_PREDICTIONS if dimension == "vendor" else TOPIC_PREDICTIONS
        )
        if actual_predictions != expected_predictions:
            raise TopicQualityError(
                f"{dimension}/{target}: strata must cover {sorted(expected_predictions)}"
            )

    ids: set[str] = set()
    relations: set[tuple[str, str, str]] = set()
    item_bindings: dict[str, tuple[str, str]] = {}
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for sample in samples:
        if sample.id in ids:
            raise TopicQualityError(f"duplicate sample id: {sample.id}")
        ids.add(sample.id)
        relation_key = (sample.dimension, sample.target_slug, sample.content_item_id)
        if relation_key in relations:
            raise TopicQualityError("duplicate target/item relation: " + "/".join(relation_key))
        relations.add(relation_key)
        binding = (sample.current_revision_id, sample.content_sha256)
        previous_binding = item_bindings.setdefault(sample.content_item_id, binding)
        if previous_binding != binding:
            raise TopicQualityError(
                f"{sample.content_item_id}: revision/hash drift inside the frozen dataset"
            )
        counts[sample.stratum] += 1
        expected_population = stratum_populations.get(sample.stratum)
        if expected_population is None:
            raise TopicQualityError(f"{sample.id}: sample references an undeclared stratum")
        if expected_population != sample.population_size:
            raise TopicQualityError(f"{sample.id}: population_size differs from its stratum")

    for stratum, population in stratum_populations.items():
        count = counts[stratum]
        expected = min(per_stratum, population)
        if count != expected:
            label = "/".join(stratum)
            raise TopicQualityError(f"{label}: expected {expected} samples, found {count}")

    return RelationDataset(
        schema_version=1,
        dataset_id=dataset_id.strip(),
        seed=seed.strip(),
        per_stratum=per_stratum,
        strata=tuple(strata),
        samples=samples,
        document=document,
    )


def audit_corpus_bindings(connection: Any, dataset: RelationDataset) -> dict[str, int]:
    """Reject annotations whose target set or original content snapshot has drifted."""
    expected = {
        sample.content_item_id: (sample.current_revision_id, sample.content_sha256)
        for sample in dataset.samples
    }
    expected_targets = {(dimension, target) for dimension, target, _prediction, _ in dataset.strata}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 'vendor', slug FROM vendor
            UNION ALL
            SELECT 'topic', slug FROM topic WHERE parent_id IS NOT NULL
            """
        )
        actual_targets = {(str(row[0]), str(row[1])) for row in cursor.fetchall()}
        cursor.execute(
            """
            SELECT ci.id::text, ci.current_revision_id::text, cr.content_sha256
              FROM content_item ci
              JOIN content_revision cr ON cr.id = ci.current_revision_id
             WHERE ci.id = ANY(%s::uuid[])
            """,
            (list(expected),),
        )
        actual = {str(row[0]): (str(row[1]), str(row[2])) for row in cursor.fetchall()}

    missing_targets = sorted(actual_targets - expected_targets)
    retired_targets = sorted(expected_targets - actual_targets)
    missing = sorted(set(expected) - set(actual))
    stale = sorted(
        item_id
        for item_id in expected.keys() & actual.keys()
        if expected[item_id] != actual[item_id]
    )
    if missing_targets or retired_targets or missing or stale:
        details: list[str] = []
        if missing_targets:
            details.append(
                f"missing_targets={len(missing_targets)} first={'/'.join(missing_targets[0])}"
            )
        if retired_targets:
            details.append(
                f"retired_targets={len(retired_targets)} first={'/'.join(retired_targets[0])}"
            )
        if missing:
            details.append(f"missing_items={len(missing)} first={missing[0]}")
        if stale:
            details.append(f"stale_revisions={len(stale)} first={stale[0]}")
        raise TopicQualityError("corpus binding check failed: " + "; ".join(details))
    return {
        "targets": len(expected_targets),
        "unique_items": len(expected),
        "missing_items": 0,
        "stale_revisions": 0,
    }


REVIEW_BINDING_FIELDS = (
    "dimension",
    "target_slug",
    "content_item_id",
    "current_revision_id",
    "content_sha256",
    "canonical_url",
    "title",
    "source_name",
    "original_excerpt",
)


def build_review_packet(dataset: RelationDataset, reviewer: str) -> dict[str, Any]:
    """Create a shuffled blind packet without predictions or classifier metadata."""
    reviewer_id = reviewer.strip()
    if not reviewer_id:
        raise TopicQualityError("reviewer must be non-empty")
    raw_by_id = {str(row["id"]): row for row in dataset.document["samples"]}
    samples: list[dict[str, Any]] = []
    for sample in dataset.samples:
        raw = cast(dict[str, Any], raw_by_id[sample.id])
        row: dict[str, Any] = {"id": sample.id}
        row.update({field: raw[field] for field in REVIEW_BINDING_FIELDS})
        row.update(
            {"gold_label": None, "reviewer": reviewer_id, "reviewed_at": None, "notes": None}
        )
        samples.append(row)
    random.Random(f"{dataset.dataset_id}:{reviewer_id}").shuffle(samples)
    return {
        "schema_version": 1,
        "packet_type": "topic-map-blind-review",
        "dataset_id": dataset.dataset_id,
        "reviewer": reviewer_id,
        "instructions": "Do not inspect predicted labels. Judge the original source independently.",
        "samples": samples,
    }


def load_review_packet(path: str | Path, dataset: RelationDataset) -> dict[str, Any]:
    """Validate an independently completed blind-review packet against the frozen set."""
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TopicQualityError(f"{source}: review packet root must be an object")
    packet = cast(dict[str, Any], payload)
    if packet.get("schema_version") != 1 or packet.get("packet_type") != "topic-map-blind-review":
        raise TopicQualityError(f"{source}: unsupported review packet schema")
    if packet.get("dataset_id") != dataset.dataset_id:
        raise TopicQualityError(f"{source}: dataset_id does not match the frozen set")
    reviewer = packet.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise TopicQualityError(f"{source}: reviewer must be non-empty")
    if reviewer != reviewer.strip():
        raise TopicQualityError(f"{source}: reviewer must not have surrounding whitespace")
    raw_samples = packet.get("samples")
    if not isinstance(raw_samples, list):
        raise TopicQualityError(f"{source}: samples must be a list")

    expected_by_id = {
        str(row["id"]): cast(dict[str, Any], row) for row in dataset.document["samples"]
    }
    reviewed: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_samples):
        if not isinstance(raw, dict):
            raise TopicQualityError(f"{source}: samples[{index}] must be an object")
        row = cast(dict[str, Any], raw)
        sample_id = _required_text(row, "id", sample_id=f"review.samples[{index}]")
        forbidden = sorted(
            {
                "predicted_label",
                "population_size",
                "confidence",
                "reason_code",
                "classifier_version",
            }
            & row.keys()
        )
        if forbidden:
            raise TopicQualityError(
                f"{source}: {sample_id} exposes blind-review fields {forbidden}"
            )
        if sample_id in reviewed:
            raise TopicQualityError(f"{source}: duplicate review sample id {sample_id}")
        expected = expected_by_id.get(sample_id)
        if expected is None:
            raise TopicQualityError(f"{source}: unknown review sample id {sample_id}")
        for field in REVIEW_BINDING_FIELDS:
            if row.get(field) != expected.get(field):
                raise TopicQualityError(f"{source}: {sample_id} changed protected field {field}")
        if row.get("reviewer") != reviewer:
            raise TopicQualityError(f"{source}: {sample_id} reviewer differs from packet reviewer")
        gold = row.get("gold_label")
        allowed = VENDOR_GOLD if expected["dimension"] == "vendor" else TOPIC_GOLD
        if gold is not None and gold not in allowed:
            raise TopicQualityError(f"{source}: {sample_id} has invalid gold_label {gold!r}")
        reviewed_at = row.get("reviewed_at")
        if gold is None:
            if reviewed_at is not None:
                raise TopicQualityError(f"{source}: {sample_id} is pending but has reviewed_at")
        else:
            if not isinstance(reviewed_at, str):
                raise TopicQualityError(f"{source}: {sample_id} needs reviewed_at")
            try:
                parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise TopicQualityError(
                    f"{source}: {sample_id} reviewed_at is not ISO-8601"
                ) from exc
            if parsed.tzinfo is None:
                raise TopicQualityError(f"{source}: {sample_id} reviewed_at needs a timezone")
        reviewed[sample_id] = row
    missing = sorted(set(expected_by_id) - set(reviewed))
    if missing:
        raise TopicQualityError(f"{source}: missing {len(missing)} samples; first={missing[0]}")
    return packet


def compare_review_packets(
    dataset: RelationDataset, packet_a: dict[str, Any], packet_b: dict[str, Any]
) -> dict[str, Any]:
    """Report independent-review progress, agreement and adjudication candidates."""
    reviewer_a = str(packet_a["reviewer"])
    reviewer_b = str(packet_b["reviewer"])
    if reviewer_a == reviewer_b:
        raise TopicQualityError("blind review packets must use two different reviewers")
    rows_a = {str(row["id"]): row for row in packet_a["samples"]}
    rows_b = {str(row["id"]): row for row in packet_b["samples"]}
    source_by_id = {
        str(row["id"]): cast(dict[str, Any], row) for row in dataset.document["samples"]
    }
    pending = [
        sample.id
        for sample in dataset.samples
        if not rows_a[sample.id]["gold_label"] or not rows_b[sample.id]["gold_label"]
    ]
    disagreements: list[dict[str, Any]] = []
    agreed = 0
    for sample in dataset.samples:
        label_a = rows_a[sample.id]["gold_label"]
        label_b = rows_b[sample.id]["gold_label"]
        if label_a is None or label_b is None:
            continue
        if label_a == label_b:
            agreed += 1
            continue
        source = source_by_id[sample.id]
        row: dict[str, Any] = {"id": sample.id}
        row.update({field: source[field] for field in REVIEW_BINDING_FIELDS})
        row.update(
            {
                "reviewer_a": reviewer_a,
                "label_a": label_a,
                "reviewer_b": reviewer_b,
                "label_b": label_b,
                "gold_label": None,
                "reviewer": None,
                "reviewed_at": None,
                "notes": None,
            }
        )
        disagreements.append(row)
    complete = len(dataset.samples) - len(pending)
    agreement_by_dimension = {
        dimension: _reviewer_agreement(
            [
                (rows_a[sample.id]["gold_label"], rows_b[sample.id]["gold_label"])
                for sample in dataset.samples
                if sample.dimension == dimension
                and rows_a[sample.id]["gold_label"] is not None
                and rows_b[sample.id]["gold_label"] is not None
            ]
        )
        for dimension in ("vendor", "topic")
    }
    return {
        "schema_version": 1,
        "packet_type": "topic-map-adjudication",
        "dataset_id": dataset.dataset_id,
        "reviewers": [reviewer_a, reviewer_b],
        "status": "ready_for_adjudication" if not pending else "pending_independent_review",
        "samples": len(dataset.samples),
        "completed_by_both": complete,
        "pending": len(pending),
        "agreed": agreed,
        "disagreements": len(disagreements),
        "agreement_rate": round(agreed / complete, 6) if complete else None,
        "agreement_by_dimension": agreement_by_dimension,
        "items": disagreements,
    }


def _reviewer_agreement(pairs: list[tuple[str, str]]) -> dict[str, float | int | None]:
    if not pairs:
        return {"completed": 0, "agreement_rate": None, "cohen_kappa": None}
    observed = sum(left == right for left, right in pairs) / len(pairs)
    left_counts: dict[str, int] = defaultdict(int)
    right_counts: dict[str, int] = defaultdict(int)
    for left, right in pairs:
        left_counts[left] += 1
        right_counts[right] += 1
    labels = set(left_counts) | set(right_counts)
    expected = sum(
        (left_counts[label] / len(pairs)) * (right_counts[label] / len(pairs)) for label in labels
    )
    kappa = None if math.isclose(expected, 1.0) else (observed - expected) / (1 - expected)
    return {
        "completed": len(pairs),
        "agreement_rate": round(observed, 6),
        "cohen_kappa": round(kappa, 6) if kappa is not None else None,
    }


def finalize_reviewed_dataset(
    dataset: RelationDataset,
    packet_a: dict[str, Any],
    packet_b: dict[str, Any],
    adjudication: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge two complete blind reviews and adjudication into full and public-safe artifacts."""
    comparison = compare_review_packets(dataset, packet_a, packet_b)
    if comparison["pending"]:
        raise TopicQualityError(
            f"independent review is incomplete: pending={comparison['pending']}"
        )
    reviewer_a, reviewer_b = cast(list[str], comparison["reviewers"])
    rows_a = {str(row["id"]): row for row in packet_a["samples"]}
    rows_b = {str(row["id"]): row for row in packet_b["samples"]}
    samples_by_id = {sample.id: sample for sample in dataset.samples}
    adjudicated: dict[str, dict[str, Any]] = {}
    if comparison["disagreements"]:
        if adjudication is None:
            raise TopicQualityError("disagreements require an adjudication packet")
        if adjudication.get("schema_version") != 1:
            raise TopicQualityError("adjudication schema_version must be 1")
        if adjudication.get("packet_type") != "topic-map-adjudication":
            raise TopicQualityError("adjudication packet_type is invalid")
        if adjudication.get("dataset_id") != dataset.dataset_id:
            raise TopicQualityError("adjudication dataset_id does not match the frozen set")
        if adjudication.get("reviewers") != [reviewer_a, reviewer_b]:
            raise TopicQualityError("adjudication reviewers do not match the blind-review packets")
        items = adjudication.get("items")
        if not isinstance(items, list):
            raise TopicQualityError("adjudication items must be a list")
        expected_rows = {str(row["id"]): row for row in comparison["items"]}
        expected_disagreements = set(expected_rows)
        for raw in items:
            if not isinstance(raw, dict):
                raise TopicQualityError("adjudication item must be an object")
            row = cast(dict[str, Any], raw)
            sample_id = str(row.get("id", ""))
            if sample_id not in expected_disagreements or sample_id in adjudicated:
                raise TopicQualityError(f"invalid adjudication sample {sample_id!r}")
            expected = expected_rows[sample_id]
            protected_fields = (
                *REVIEW_BINDING_FIELDS,
                "reviewer_a",
                "label_a",
                "reviewer_b",
                "label_b",
            )
            for field in protected_fields:
                if row.get(field) != expected.get(field):
                    raise TopicQualityError(
                        f"{sample_id}: adjudication changed protected field {field}"
                    )
            forbidden = sorted(
                set(row)
                & {
                    "predicted_label",
                    "population_size",
                    "confidence",
                    "reason",
                    "classifier",
                }
            )
            if forbidden:
                raise TopicQualityError(
                    f"{sample_id}: adjudication exposes blind-review fields {forbidden}"
                )
            gold = row.get("gold_label")
            sample = samples_by_id[sample_id]
            allowed = VENDOR_GOLD if sample.dimension == "vendor" else TOPIC_GOLD
            if gold not in allowed:
                raise TopicQualityError(f"{sample_id}: adjudication gold_label is invalid")
            reviewer = row.get("reviewer")
            if (
                not isinstance(reviewer, str)
                or not reviewer.strip()
                or reviewer.strip() in {reviewer_a, reviewer_b}
            ):
                raise TopicQualityError(f"{sample_id}: adjudicator must be an independent reviewer")
            reviewed_at = row.get("reviewed_at")
            if not isinstance(reviewed_at, str):
                raise TopicQualityError(f"{sample_id}: adjudication needs reviewed_at")
            try:
                parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise TopicQualityError(
                    f"{sample_id}: adjudication reviewed_at is not ISO-8601"
                ) from exc
            if parsed.tzinfo is None:
                raise TopicQualityError(f"{sample_id}: adjudication reviewed_at needs a timezone")
            adjudicated[sample_id] = row
        missing = expected_disagreements - set(adjudicated)
        if missing:
            raise TopicQualityError(f"adjudication is incomplete: pending={len(missing)}")

    full = deepcopy(dataset.document)
    public_labels: list[dict[str, Any]] = []
    for row in full["samples"]:
        sample_id = str(row["id"])
        left, right = rows_a[sample_id], rows_b[sample_id]
        if left["gold_label"] == right["gold_label"]:
            reviewed_at = max(
                (str(left["reviewed_at"]), str(right["reviewed_at"])),
                key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                    UTC
                ),
            )
            winner = {
                "gold_label": left["gold_label"],
                "reviewer": f"{reviewer_a}+{reviewer_b}",
                "reviewed_at": reviewed_at,
                "notes": None,
            }
        else:
            winner = adjudicated[sample_id]
        row["gold_label"] = winner["gold_label"]
        row["reviewer"] = winner["reviewer"]
        row["reviewed_at"] = winner["reviewed_at"]
        row["notes"] = winner.get("notes")
        public_labels.append(
            {
                "id": sample_id,
                "dimension": row["dimension"],
                "target_slug": row["target_slug"],
                "predicted_label": row["predicted_label"],
                "population_size": row["population_size"],
                "content_item_id": row["content_item_id"],
                "current_revision_id": row["current_revision_id"],
                "content_sha256": row["content_sha256"],
                "canonical_url": row["canonical_url"],
                "gold_label": row["gold_label"],
                "reviewed_at": row["reviewed_at"],
            }
        )
    labels = {
        "schema_version": 1,
        "artifact_type": "topic-map-final-labels",
        "dataset_id": dataset.dataset_id,
        "reviewer_count": 2,
        "agreement_rate": comparison["agreement_rate"],
        "disagreements": comparison["disagreements"],
        "labels": public_labels,
    }
    return full, labels


def stable_sample_id(
    dimension: str, target_slug: str, predicted_label: str, content_item_id: str
) -> str:
    """Return an opaque deterministic id; rerunning the same snapshot is diff-free."""
    material = f"{dimension}:{target_slug}:{predicted_label}:{content_item_id}".encode()
    return "TMG-" + hashlib.sha256(material).hexdigest()[:16]


def clean_excerpt(value: object, *, limit: int = 700) -> str:
    """Keep an auditable original-body excerpt compact and YAML-friendly."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_dataset(
    connection: Any,
    *,
    per_stratum: int = 20,
    seed: str = "topic-map-golden-v1",
) -> dict[str, Any]:
    """Freeze deterministic vendor/topic strata from the current PostgreSQL corpus."""
    if per_stratum < 1:
        raise TopicQualityError("per_stratum must be positive")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*), max(COALESCE(enriched_at, observed_at))
              FROM content_item
             WHERE duplicate_of_id IS NULL
               AND enrichment_state = 'ENRICHED'
               AND current_revision_id IS NOT NULL
            """
        )
        corpus_count, snapshot_at = cursor.fetchone()
        cursor.execute("SELECT slug FROM vendor ORDER BY display_order, slug")
        vendors = [str(row[0]) for row in cursor.fetchall()]
        cursor.execute("SELECT slug FROM topic WHERE parent_id IS NOT NULL ORDER BY slug")
        topics = [str(row[0]) for row in cursor.fetchall()]

    snapshot_text = snapshot_at.isoformat() if snapshot_at is not None else "empty"
    samples: list[dict[str, Any]] = []
    strata: list[dict[str, Any]] = []
    vendor_predictions: tuple[VendorPrediction, ...] = (
        "primary",
        "related",
        "mention",
        "unmatched",
    )
    topic_predictions: tuple[TopicPrediction, ...] = ("public", "suppressed", "unmatched")
    for vendor in vendors:
        for vendor_prediction in vendor_predictions:
            selected = _sample_vendor_stratum(
                connection,
                target_slug=vendor,
                predicted_label=vendor_prediction,
                limit=per_stratum,
                seed=seed,
            )
            population = int(selected[0]["population_size"]) if selected else 0
            strata.append(
                {
                    "dimension": "vendor",
                    "target_slug": vendor,
                    "predicted_label": vendor_prediction,
                    "population_size": population,
                }
            )
            samples.extend(selected)
    for topic in topics:
        for topic_prediction in topic_predictions:
            selected = _sample_topic_stratum(
                connection,
                target_slug=topic,
                predicted_label=topic_prediction,
                limit=per_stratum,
                seed=seed,
            )
            population = int(selected[0]["population_size"]) if selected else 0
            strata.append(
                {
                    "dimension": "topic",
                    "target_slug": topic,
                    "predicted_label": topic_prediction,
                    "population_size": population,
                }
            )
            samples.extend(selected)

    fingerprint = "\n".join(
        f"{sample['id']}:{sample['content_sha256']}:{sample['population_size']}"
        for sample in samples
    )
    snapshot_hash = hashlib.sha256(
        f"{corpus_count}:{snapshot_text}:{seed}:{per_stratum}\n{fingerprint}".encode()
    ).hexdigest()[:20]
    snapshot_id = (
        snapshot_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        if snapshot_at is not None
        else "empty"
    )

    return {
        "schema_version": 1,
        "dataset_id": f"topic-map-relations-{snapshot_id}-{snapshot_hash}",
        "seed": seed,
        "per_stratum": per_stratum,
        "snapshot": {
            "eligible_content_items": int(corpus_count),
            "latest_enrichment_or_observation": snapshot_text,
            "vendor_targets": len(vendors),
            "topic_targets": len(topics),
        },
        "annotation_policy_version": "topic-map-relations-v1",
        "strata": strata,
        "samples": samples,
    }


def _base_sample(row: tuple[Any, ...], *, dimension: Dimension, target_slug: str) -> dict[str, Any]:
    (
        content_item_id,
        current_revision_id,
        content_sha256,
        canonical_url,
        predicted_label,
        population_size,
        title,
        source_name,
        source_tier,
        published_at,
        original_body,
        confidence,
        reason_code,
        classifier_version,
    ) = row
    item_id = str(content_item_id)
    prediction = str(predicted_label)
    return {
        "id": stable_sample_id(dimension, target_slug, prediction, item_id),
        "dimension": dimension,
        "target_slug": target_slug,
        "predicted_label": prediction,
        "population_size": int(population_size),
        "content_item_id": item_id,
        "current_revision_id": str(current_revision_id),
        "content_sha256": str(content_sha256),
        "canonical_url": str(canonical_url),
        "title": clean_excerpt(title, limit=240),
        "source_name": str(source_name),
        "source_tier": str(source_tier),
        "published_at": published_at.isoformat() if published_at is not None else None,
        "original_excerpt": clean_excerpt(original_body),
        "confidence": float(confidence) if confidence is not None else None,
        "reason_code": str(reason_code) if reason_code is not None else None,
        "classifier_version": (str(classifier_version) if classifier_version is not None else None),
        "gold_label": None,
        "reviewer": None,
        "reviewed_at": None,
        "notes": None,
    }


def _sample_vendor_stratum(
    connection: Any,
    *,
    target_slug: str,
    predicted_label: VendorPrediction,
    limit: int,
    seed: str,
) -> list[dict[str, Any]]:
    relation_filter = (
        "ivr.relation_level IS NULL"
        if predicted_label == "unmatched"
        else "ivr.relation_level = %s"
    )
    params: list[object] = [target_slug]
    if predicted_label != "unmatched":
        params.append(predicted_label)
    params.extend([f"{seed}:vendor:{target_slug}:{predicted_label}", limit])
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT ci.id, cr.id, cr.content_sha256, ci.canonical_url,
                   COALESCE(ivr.relation_level, 'unmatched') AS predicted_label,
                   count(*) OVER () AS population_size,
                   COALESCE(ci.zh_title, ci.title), s.name, ci.source_tier,
                   COALESCE(ci.published_at, ci.observed_at),
                   CASE
                       WHEN e.name IS NOT NULL
                            AND position(lower(e.name) in lower(cr.body_text)) > 0
                       THEN substring(
                           cr.body_text
                           FROM GREATEST(
                               1,
                               position(lower(e.name) in lower(cr.body_text)) - 250
                           )
                           FOR 700
                       )
                       ELSE cr.body_text
                   END,
                   ivr.confidence, ivr.reason_code, ivr.classifier_version
              FROM content_item ci
              JOIN source s ON s.id = ci.source_id
              JOIN content_revision cr ON cr.id = ci.current_revision_id
              LEFT JOIN item_vendor_relation ivr
                ON ivr.content_item_id = ci.id AND ivr.vendor_slug = %s
              LEFT JOIN entity e ON e.slug = ivr.matched_entity_slug
             WHERE ci.duplicate_of_id IS NULL
               AND ci.enrichment_state = 'ENRICHED'
               AND {relation_filter}
             ORDER BY md5(ci.id::text || %s)
             LIMIT %s
            """,
            params,
        )
        rows = cursor.fetchall()
    return [_base_sample(row, dimension="vendor", target_slug=target_slug) for row in rows]


def _sample_topic_stratum(
    connection: Any,
    *,
    target_slug: str,
    predicted_label: TopicPrediction,
    limit: int,
    seed: str,
) -> list[dict[str, Any]]:
    if predicted_label == "public":
        relation_filter = "pit.content_item_id IS NOT NULL"
    elif predicted_label == "suppressed":
        relation_filter = "it.content_item_id IS NOT NULL AND pit.content_item_id IS NULL"
    else:
        relation_filter = "it.content_item_id IS NULL"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT ci.id, cr.id, cr.content_sha256, ci.canonical_url,
                   CASE
                       WHEN pit.content_item_id IS NOT NULL THEN 'public'
                       WHEN it.content_item_id IS NOT NULL THEN 'suppressed'
                       ELSE 'unmatched'
                   END AS predicted_label,
                   count(*) OVER () AS population_size,
                   COALESCE(ci.zh_title, ci.title), s.name, ci.source_tier,
                   COALESCE(ci.published_at, ci.observed_at), cr.body_text,
                   it.confidence, NULL::text AS reason_code,
                   ci.prompt_version AS classifier_version
              FROM content_item ci
              JOIN source s ON s.id = ci.source_id
              JOIN content_revision cr ON cr.id = ci.current_revision_id
              LEFT JOIN topic t ON t.slug = %s
              LEFT JOIN item_topic it
                ON it.content_item_id = ci.id AND it.topic_id = t.id
              LEFT JOIN public_item_topic pit
                ON pit.content_item_id = ci.id AND pit.topic_id = t.id
             WHERE ci.duplicate_of_id IS NULL
               AND ci.enrichment_state = 'ENRICHED'
               AND {relation_filter}
             ORDER BY md5(ci.id::text || %s)
             LIMIT %s
            """,
            (target_slug, f"{seed}:topic:{target_slug}:{predicted_label}", limit),
        )
        rows = cursor.fetchall()
    return [_base_sample(row, dimension="topic", target_slug=target_slug) for row in rows]


def evaluate_dataset(dataset: RelationDataset) -> dict[str, Any]:
    """Compute weighted corpus estimates, or explicitly report pending review."""
    pending = [sample for sample in dataset.samples if sample.gold_label is None]
    reviewed = [sample for sample in dataset.samples if sample.gold_label is not None]
    sampled_strata: dict[tuple[str, str, str], list[RelationSample]] = defaultdict(list)
    for sample in dataset.samples:
        sampled_strata[sample.stratum].append(sample)

    coverage = {
        "/".join((dimension, target, prediction)): {
            "population": population,
            "sampled": len(rows),
            "reviewed": sum(row.gold_label is not None for row in rows),
        }
        for dimension, target, prediction, population in dataset.strata
        for rows in [sampled_strata[(dimension, target, prediction)]]
    }
    result: dict[str, Any] = {
        "dataset_id": dataset.dataset_id,
        "status": "ready" if not pending else "pending_human_review",
        "samples": len(dataset.samples),
        "reviewed": len(reviewed),
        "pending": len(pending),
        "coverage": coverage,
        "metrics": {},
    }
    if pending or not reviewed:
        return result

    vendor = [sample for sample in reviewed if sample.dimension == "vendor"]
    topic = [sample for sample in reviewed if sample.dimension == "topic"]
    result["metrics"] = {
        "vendor_public": _weighted_binary_metrics(
            vendor,
            predicted_positive={"primary", "related"},
            gold_positive={"primary", "related"},
        ),
        "vendor_primary_precision": _weighted_precision(
            vendor,
            predicted_positive={"primary"},
            gold_positive={"primary"},
        ),
        "topic_public": _weighted_binary_metrics(
            topic,
            predicted_positive={"public"},
            gold_positive={"relevant"},
        ),
    }
    result["confidence_intervals_95"] = _bootstrap_confidence_intervals(
        dataset.dataset_id, reviewed
    )
    return result


def _bootstrap_confidence_intervals(
    dataset_id: str, samples: list[RelationSample], *, iterations: int = 1000
) -> dict[str, dict[str, float | None]]:
    """Return deterministic stratified-bootstrap intervals for published rates."""
    grouped: dict[tuple[str, str, str], list[RelationSample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.stratum].append(sample)
    seed = int(hashlib.sha256(f"{dataset_id}:bootstrap-v1".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    values: dict[str, list[float]] = defaultdict(list)
    for _ in range(iterations):
        draws: list[tuple[RelationSample, float]] = []
        for rows in grouped.values():
            weight = rows[0].population_size / len(rows)
            draws.extend((rng.choice(rows), weight) for _ in range(len(rows)))
        vendor = [(sample, weight) for sample, weight in draws if sample.dimension == "vendor"]
        topic = [(sample, weight) for sample, weight in draws if sample.dimension == "topic"]
        primary = _draw_precision(vendor, predicted_positive={"primary"}, gold_positive={"primary"})
        vendor_public = _draw_binary_metrics(
            vendor,
            predicted_positive={"primary", "related"},
            gold_positive={"primary", "related"},
        )
        topic_public = _draw_binary_metrics(
            topic, predicted_positive={"public"}, gold_positive={"relevant"}
        )
        for name, value in (
            ("vendor_primary_precision", primary),
            ("vendor_public_precision", vendor_public["precision"]),
            ("vendor_public_recall", vendor_public["recall"]),
            ("topic_public_precision", topic_public["precision"]),
            ("topic_public_recall", topic_public["recall"]),
        ):
            if value is not None:
                values[name].append(value)
    return {
        name: {
            "low": _percentile(series, 0.025),
            "high": _percentile(series, 0.975),
        }
        for name, series in values.items()
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise TopicQualityError("cannot calculate a percentile from no observations")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 6)


def _draw_precision(
    draws: list[tuple[RelationSample, float]],
    *,
    predicted_positive: set[str],
    gold_positive: set[str],
) -> float | None:
    predicted_weight = sum(
        weight for sample, weight in draws if sample.predicted_label in predicted_positive
    )
    if math.isclose(predicted_weight, 0.0):
        return None
    supported = sum(
        weight
        for sample, weight in draws
        if sample.predicted_label in predicted_positive and sample.gold_label in gold_positive
    )
    return supported / predicted_weight


def _draw_binary_metrics(
    draws: list[tuple[RelationSample, float]],
    *,
    predicted_positive: set[str],
    gold_positive: set[str],
) -> dict[str, float | None]:
    tp = fp = fn = 0.0
    for sample, weight in draws:
        predicted = sample.predicted_label in predicted_positive
        gold = sample.gold_label in gold_positive
        if predicted and gold:
            tp += weight
        elif predicted:
            fp += weight
        elif gold:
            fn += weight
    return {
        "precision": None if math.isclose(tp + fp, 0.0) else tp / (tp + fp),
        "recall": None if math.isclose(tp + fn, 0.0) else tp / (tp + fn),
    }


def _weights(samples: list[RelationSample]) -> dict[str, float]:
    reviewed_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for sample in samples:
        reviewed_counts[sample.stratum] += 1
    return {
        sample.id: sample.population_size / reviewed_counts[sample.stratum] for sample in samples
    }


def _weighted_precision(
    samples: list[RelationSample], *, predicted_positive: set[str], gold_positive: set[str]
) -> float | None:
    weights = _weights(samples)
    predicted_weight = sum(
        weights[sample.id] for sample in samples if sample.predicted_label in predicted_positive
    )
    if math.isclose(predicted_weight, 0.0):
        return None
    true_weight = sum(
        weights[sample.id]
        for sample in samples
        if sample.predicted_label in predicted_positive and sample.gold_label in gold_positive
    )
    return round(true_weight / predicted_weight, 6)


def _weighted_binary_metrics(
    samples: list[RelationSample], *, predicted_positive: set[str], gold_positive: set[str]
) -> dict[str, float | None]:
    weights = _weights(samples)
    tp = fp = fn = tn = 0.0
    for sample in samples:
        predicted = sample.predicted_label in predicted_positive
        gold = sample.gold_label in gold_positive
        weight = weights[sample.id]
        if predicted and gold:
            tp += weight
        elif predicted:
            fp += weight
        elif gold:
            fn += weight
        else:
            tn += weight
    precision = None if math.isclose(tp + fp, 0.0) else round(tp / (tp + fp), 6)
    recall = None if math.isclose(tp + fn, 0.0) else round(tp / (tp + fn), 6)
    return {
        "precision": precision,
        "recall": recall,
        "estimated_tp": round(tp, 3),
        "estimated_fp": round(fp, 3),
        "estimated_fn": round(fn, 3),
        "estimated_tn": round(tn, 3),
    }


def dump_dataset(payload: dict[str, Any], path: str | Path) -> None:
    """Write a stable, human-editable YAML artifact."""
    Path(path).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )

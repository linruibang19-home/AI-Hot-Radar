from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ahr.processing.topic_quality import (
    TopicQualityError,
    audit_corpus_bindings,
    build_review_packet,
    clean_excerpt,
    compare_review_packets,
    evaluate_dataset,
    finalize_reviewed_dataset,
    load_dataset,
    load_review_packet,
    stable_sample_id,
)


class _Cursor:
    def __init__(
        self,
        rows: list[tuple[str, str, str]],
        targets: list[tuple[str, str]],
    ) -> None:
        self.rows = rows
        self.targets = targets
        self.result: list[tuple[str, ...]] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, _params: object = None) -> None:
        selected = self.targets if "UNION ALL" in query else self.rows
        self.result = [tuple(row) for row in selected]

    def fetchall(self) -> list[tuple[str, ...]]:
        return self.result


class _Connection:
    def __init__(
        self,
        rows: list[tuple[str, str, str]],
        targets: list[tuple[str, str]] | None = None,
    ) -> None:
        self.rows = rows
        self.targets = targets or [("topic", "rag")]

    def cursor(self) -> _Cursor:
        return _Cursor(self.rows, self.targets)


def _sample(
    *,
    sample_id: str,
    dimension: str,
    target: str,
    prediction: str,
    population: int,
    item: str,
    gold: str | None,
) -> dict[str, object]:
    return {
        "id": sample_id,
        "dimension": dimension,
        "target_slug": target,
        "predicted_label": prediction,
        "population_size": population,
        "content_item_id": item,
        "current_revision_id": f"revision-{item}",
        "content_sha256": "a" * 64,
        "canonical_url": f"https://example.test/{item}",
        "title": f"title {item}",
        "source_name": "source",
        "original_excerpt": "verbatim evidence",
        "gold_label": gold,
        "reviewer": "reviewer@example.test" if gold else None,
        "reviewed_at": "2026-08-13T12:00:00+08:00" if gold else None,
    }


def _write(tmp_path: Path, samples: list[dict[str, object]], *, per_stratum: int = 1) -> Path:
    populations: dict[tuple[str, str, str], int] = {}
    for sample in samples:
        key = (
            str(sample["dimension"]),
            str(sample["target_slug"]),
            str(sample["predicted_label"]),
        )
        population = sample["population_size"]
        assert isinstance(population, int)
        populations[key] = population
    targets = {(dimension, target) for dimension, target, _prediction in populations}
    for dimension, target in targets:
        predictions = (
            ("primary", "related", "mention", "unmatched")
            if dimension == "vendor"
            else ("public", "suppressed", "unmatched")
        )
        for prediction in predictions:
            populations.setdefault((dimension, target, prediction), 0)
    path = tmp_path / "annotations.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "dataset_id": "test-set",
                "seed": "fixed",
                "per_stratum": per_stratum,
                "strata": [
                    {
                        "dimension": dimension,
                        "target_slug": target,
                        "predicted_label": prediction,
                        "population_size": population,
                    }
                    for (dimension, target, prediction), population in sorted(populations.items())
                ],
                "samples": samples,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_packet(tmp_path: Path, name: str, packet: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(packet, sort_keys=False), encoding="utf-8")
    return path


def test_stable_sample_id_is_reproducible_and_target_specific() -> None:
    first = stable_sample_id("vendor", "openai", "primary", "item-1")
    assert first == stable_sample_id("vendor", "openai", "primary", "item-1")
    assert first != stable_sample_id("vendor", "anthropic", "primary", "item-1")


def test_clean_excerpt_normalises_whitespace_without_hiding_truncation() -> None:
    assert clean_excerpt(" one\n\n two ") == "one two"
    assert clean_excerpt("abcdefgh", limit=5) == "abcd…"


def test_pending_dataset_is_explicitly_not_ready(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            _sample(
                sample_id="p1",
                dimension="topic",
                target="rag",
                prediction="public",
                population=1,
                item="i1",
                gold=None,
            )
        ],
    )
    report = evaluate_dataset(load_dataset(path))
    assert report["status"] == "pending_human_review"
    assert report["reviewed"] == 0
    assert report["pending"] == 1
    assert report["metrics"] == {}
    assert report["coverage"]["topic/rag/suppressed"] == {
        "population": 0,
        "sampled": 0,
        "reviewed": 0,
    }


def test_partial_review_does_not_publish_partial_metrics(tmp_path: Path) -> None:
    samples = [
        _sample(
            sample_id="reviewed",
            dimension="topic",
            target="rag",
            prediction="public",
            population=2,
            item="i1",
            gold="relevant",
        ),
        _sample(
            sample_id="pending",
            dimension="topic",
            target="rag",
            prediction="public",
            population=2,
            item="i2",
            gold=None,
        ),
    ]
    report = evaluate_dataset(load_dataset(_write(tmp_path, samples, per_stratum=2)))
    assert report["status"] == "pending_human_review"
    assert report["metrics"] == {}


def test_labels_must_match_dimension(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            _sample(
                sample_id="bad",
                dimension="topic",
                target="rag",
                prediction="primary",
                population=1,
                item="i1",
                gold=None,
            )
        ],
    )
    with pytest.raises(TopicQualityError, match="invalid for topic"):
        load_dataset(path)


def test_reviewed_at_requires_an_explicit_timezone(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="reviewed",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold="relevant",
    )
    raw["reviewed_at"] = "2026-08-13T12:00:00"
    with pytest.raises(TopicQualityError, match="reviewed_at must include a timezone"):
        load_dataset(_write(tmp_path, [raw]))


def test_duplicate_target_item_is_rejected_even_across_predictions(tmp_path: Path) -> None:
    samples = [
        _sample(
            sample_id="a",
            dimension="vendor",
            target="openai",
            prediction="primary",
            population=1,
            item="i1",
            gold=None,
        ),
        _sample(
            sample_id="b",
            dimension="vendor",
            target="openai",
            prediction="mention",
            population=1,
            item="i1",
            gold=None,
        ),
    ]
    path = _write(tmp_path, samples)
    with pytest.raises(TopicQualityError, match="duplicate target/item relation"):
        load_dataset(path)


def test_sparse_stratum_uses_population_not_requested_sample_size(tmp_path: Path) -> None:
    samples = [
        _sample(
            sample_id="a",
            dimension="vendor",
            target="cursor",
            prediction="primary",
            population=2,
            item="i1",
            gold=None,
        ),
        _sample(
            sample_id="b",
            dimension="vendor",
            target="cursor",
            prediction="primary",
            population=2,
            item="i2",
            gold=None,
        ),
    ]
    load_dataset(_write(tmp_path, samples, per_stratum=20))


def test_weighted_metrics_account_for_stratum_population(tmp_path: Path) -> None:
    samples = [
        _sample(
            sample_id="v1",
            dimension="vendor",
            target="openai",
            prediction="primary",
            population=10,
            item="i1",
            gold="primary",
        ),
        _sample(
            sample_id="v2",
            dimension="vendor",
            target="openai",
            prediction="unmatched",
            population=90,
            item="i2",
            gold="primary",
        ),
        _sample(
            sample_id="t1",
            dimension="topic",
            target="rag",
            prediction="public",
            population=20,
            item="i3",
            gold="relevant",
        ),
        _sample(
            sample_id="t2",
            dimension="topic",
            target="rag",
            prediction="unmatched",
            population=80,
            item="i4",
            gold="unrelated",
        ),
    ]
    report = evaluate_dataset(load_dataset(_write(tmp_path, samples)))
    assert report["status"] == "ready"
    assert report["metrics"]["vendor_primary_precision"] == 1.0
    assert report["metrics"]["vendor_public"] == {
        "precision": 1.0,
        "recall": 0.1,
        "estimated_tp": 10.0,
        "estimated_fp": 0.0,
        "estimated_fn": 90.0,
        "estimated_tn": 0.0,
    }
    assert report["metrics"]["topic_public"]["precision"] == 1.0
    assert report["metrics"]["topic_public"]["recall"] == 1.0


def test_corpus_binding_audit_accepts_the_frozen_revision(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="00000000-0000-0000-0000-000000000001",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    result = audit_corpus_bindings(
        _Connection(
            [
                (
                    str(raw["content_item_id"]),
                    str(raw["current_revision_id"]),
                    str(raw["content_sha256"]),
                )
            ]
        ),
        dataset,
    )
    assert result == {
        "targets": 1,
        "unique_items": 1,
        "missing_items": 0,
        "stale_revisions": 0,
    }


def test_corpus_binding_audit_rejects_a_changed_revision(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="00000000-0000-0000-0000-000000000001",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    with pytest.raises(TopicQualityError, match="stale_revisions=1"):
        audit_corpus_bindings(
            _Connection([(str(raw["content_item_id"]), "new-revision", "b" * 64)]),
            dataset,
        )


def test_corpus_binding_audit_rejects_target_taxonomy_drift(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="00000000-0000-0000-0000-000000000001",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    with pytest.raises(TopicQualityError, match="missing_targets=1 first=topic/agent"):
        audit_corpus_bindings(
            _Connection(
                [
                    (
                        str(raw["content_item_id"]),
                        str(raw["current_revision_id"]),
                        str(raw["content_sha256"]),
                    )
                ],
                targets=[("topic", "rag"), ("topic", "agent")],
            ),
            dataset,
        )


def test_blind_review_packet_hides_predictions_and_is_reproducible(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    first = build_review_packet(dataset, "reviewer-a")
    second = build_review_packet(dataset, "reviewer-a")
    assert first == second
    assert "predicted_label" not in first["samples"][0]
    assert "confidence" not in first["samples"][0]
    assert first["samples"][0]["reviewer"] == "reviewer-a"


def test_review_packet_rejects_changed_protected_evidence(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    packet = build_review_packet(dataset, "reviewer-a")
    packet["samples"][0]["original_excerpt"] = "rewritten"
    with pytest.raises(TopicQualityError, match="changed protected field original_excerpt"):
        load_review_packet(_write_packet(tmp_path, "review.yaml", packet), dataset)


def test_review_packet_rejects_prediction_leakage(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    packet = build_review_packet(dataset, "reviewer-a")
    packet["samples"][0]["predicted_label"] = "public"
    with pytest.raises(TopicQualityError, match="exposes blind-review fields"):
        load_review_packet(_write_packet(tmp_path, "review.yaml", packet), dataset)


def test_review_comparison_requires_independent_reviewers(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    packet = build_review_packet(dataset, "same-reviewer")
    with pytest.raises(TopicQualityError, match="two different reviewers"):
        compare_review_packets(dataset, packet, packet)


def test_review_packet_rejects_ambiguous_reviewer_whitespace(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    packet = build_review_packet(dataset, "reviewer-a")
    packet["reviewer"] = " reviewer-a "
    packet["samples"][0]["reviewer"] = " reviewer-a "
    with pytest.raises(TopicQualityError, match="surrounding whitespace"):
        load_review_packet(_write_packet(tmp_path, "review.yaml", packet), dataset)


def test_review_comparison_lists_disagreements_without_prediction(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    left = build_review_packet(dataset, "reviewer-a")
    right = build_review_packet(dataset, "reviewer-b")
    left["samples"][0].update(
        {"gold_label": "relevant", "reviewed_at": "2026-08-13T17:00:00+08:00"}
    )
    right["samples"][0].update(
        {"gold_label": "unrelated", "reviewed_at": "2026-08-13T17:01:00+08:00"}
    )
    report = compare_review_packets(dataset, left, right)
    assert report["status"] == "ready_for_adjudication"
    assert report["disagreements"] == 1
    assert report["agreement_rate"] == 0.0
    assert report["agreement_by_dimension"]["topic"] == {
        "completed": 1,
        "agreement_rate": 0.0,
        "cohen_kappa": 0.0,
    }
    assert report["agreement_by_dimension"]["vendor"]["completed"] == 0
    assert "predicted_label" not in report["items"][0]


def test_finalize_requires_complete_adjudication_and_emits_public_safe_labels(
    tmp_path: Path,
) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    left = build_review_packet(dataset, "reviewer-a")
    right = build_review_packet(dataset, "reviewer-b")
    left["samples"][0].update(
        {"gold_label": "relevant", "reviewed_at": "2026-08-13T17:00:00+08:00"}
    )
    right["samples"][0].update(
        {"gold_label": "unrelated", "reviewed_at": "2026-08-13T17:01:00+08:00"}
    )
    with pytest.raises(TopicQualityError, match="require an adjudication"):
        finalize_reviewed_dataset(dataset, left, right, None)

    adjudication = compare_review_packets(dataset, left, right)
    adjudication["items"][0].update(
        {
            "gold_label": "relevant",
            "reviewer": " ",
            "reviewed_at": "2026-08-13T18:00:00+08:00",
        }
    )
    with pytest.raises(TopicQualityError, match="adjudicator must be an independent reviewer"):
        finalize_reviewed_dataset(dataset, left, right, adjudication)

    adjudication["items"][0]["original_excerpt"] = "tampered evidence"
    adjudication["items"][0].update(
        {
            "gold_label": "relevant",
            "reviewer": "adjudicator",
            "reviewed_at": "2026-08-13T18:00:00+08:00",
        }
    )
    with pytest.raises(TopicQualityError, match="changed protected field original_excerpt"):
        finalize_reviewed_dataset(dataset, left, right, adjudication)

    adjudication = compare_review_packets(dataset, left, right)
    adjudication["items"][0].update(
        {
            "gold_label": "relevant",
            "reviewer": "adjudicator",
            "reviewed_at": "2026-08-13T18:00:00+08:00",
        }
    )
    full, labels = finalize_reviewed_dataset(dataset, left, right, adjudication)
    assert full["samples"][0]["gold_label"] == "relevant"
    assert labels["labels"][0]["gold_label"] == "relevant"
    assert "original_excerpt" not in labels["labels"][0]
    assert "reviewer" not in labels["labels"][0]
    assert "reviewer_fingerprint" not in labels["labels"][0]
    assert labels["reviewer_count"] == 2
    assert labels["disagreements"] == 1


def test_finalize_uses_latest_review_time_across_timezones(tmp_path: Path) -> None:
    raw = _sample(
        sample_id="p1",
        dimension="topic",
        target="rag",
        prediction="public",
        population=1,
        item="i1",
        gold=None,
    )
    dataset = load_dataset(_write(tmp_path, [raw]))
    left = build_review_packet(dataset, "reviewer-a")
    right = build_review_packet(dataset, "reviewer-b")
    left["samples"][0].update(
        {"gold_label": "relevant", "reviewed_at": "2026-08-13T10:30:00+00:00"}
    )
    right["samples"][0].update(
        {"gold_label": "relevant", "reviewed_at": "2026-08-13T18:00:00+08:00"}
    )

    full, _ = finalize_reviewed_dataset(dataset, left, right, None)

    assert full["samples"][0]["reviewed_at"] == "2026-08-13T10:30:00+00:00"


def test_ready_metrics_include_deterministic_bootstrap_intervals(tmp_path: Path) -> None:
    samples = [
        _sample(
            sample_id="v1",
            dimension="vendor",
            target="openai",
            prediction="primary",
            population=1,
            item="i1",
            gold="primary",
        ),
        _sample(
            sample_id="t1",
            dimension="topic",
            target="rag",
            prediction="public",
            population=1,
            item="i2",
            gold="relevant",
        ),
    ]
    dataset = load_dataset(_write(tmp_path, samples))
    first = evaluate_dataset(dataset)
    second = evaluate_dataset(dataset)
    assert first["confidence_intervals_95"] == second["confidence_intervals_95"]
    assert first["confidence_intervals_95"]["vendor_primary_precision"] == {
        "low": 1.0,
        "high": 1.0,
    }

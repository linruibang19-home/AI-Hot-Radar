"""Determinism boundaries for the specialist candidate-snapshot A/B."""

from ahr.rag.eval.specialist_ab import _merge_distractors, _snapshot_hash
from ahr.rag.retrieval import ChunkHit


def _hit(chunk_id: str, item_id: str, channel: str) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        content_item_id=item_id,
        score=0.5,
        title=chunk_id,
        source_name="source",
        channels=(channel,),
    )


def test_snapshot_hash_is_stable_across_mapping_order_only() -> None:
    left = [{"question_id": "Q1", "channels": {"dense": ["a"], "sparse": ["b"]}}]
    right = [{"channels": {"sparse": ["b"], "dense": ["a"]}, "question_id": "Q1"}]
    assert _snapshot_hash(left) == _snapshot_hash(right)


def test_snapshot_hash_changes_when_candidate_order_changes() -> None:
    left = [{"question_id": "Q1", "channels": {"dense": ["a", "b"]}}]
    right = [{"question_id": "Q1", "channels": {"dense": ["b", "a"]}}]
    assert _snapshot_hash(left) != _snapshot_hash(right)


def test_distractors_enter_the_budget_without_duplicating_existing_chunks() -> None:
    existing = [_hit("c1", "i1", "dense"), _hit("c2", "i2", "sparse")]
    distractors = [
        _hit("c2", "i2", "annotated_distractor"),
        _hit("c3", "i3", "annotated_distractor"),
    ]
    merged = _merge_distractors(existing, distractors)
    assert [hit.chunk_id for hit in merged] == ["c2", "c3", "c1"]

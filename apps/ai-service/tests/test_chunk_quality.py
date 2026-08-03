"""Chunk quality for retrieval (M4 step 0).

Measured against the stored corpus before writing any retrieval code: 849 of
3847 chunks were under 50 tokens and 302 exceeded what the embedding provider
would read. Both make the index quietly wrong rather than broken, so they are
pinned here.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ahr.processing.chunking import (
    HARD_MAX_TOKENS,
    MAX_TOKENS,
    MIN_TOKENS,
    chunk_document,
    estimate_tokens,
)
from ahr.rag.context import MAX_HEADING_SEGMENTS, build_embedding_text


def changelog(entries: int) -> str:
    """A release note: one heading, many one-line bullets. The shape that
    produced most of the corpus's unusable chunks."""
    lines = ["## Bug Fixes", ""]
    lines += [f"- fix issue number {i} in the parser module" for i in range(entries)]
    return "\n".join(lines)


# --- short-chunk merging --------------------------------------------------


def test_a_changelog_does_not_become_a_pile_of_fragments() -> None:
    chunks = chunk_document(changelog(24))
    tiny = [c for c in chunks if c.token_count < 50]
    assert not tiny, f"{len(tiny)} fragments under 50 tokens"


def test_short_chunks_merge_beyond_just_the_last_one() -> None:
    """Only the trailing chunk used to fold, so a twenty-bullet changelog kept
    nineteen fragments."""
    chunks = chunk_document(changelog(40))
    assert all(c.token_count >= MIN_TOKENS or len(chunks) == 1 for c in chunks)


def test_merging_never_crosses_a_heading() -> None:
    """Joining sections would undo the structure-aware split entirely."""
    document = "## Alpha\n\n- one small bullet\n\n## Beta\n\n- another small bullet"
    for chunk in chunk_document(document):
        assert len(set(map(tuple, [chunk.heading_path]))) == 1


def test_merging_respects_the_upper_bound() -> None:
    chunks = chunk_document(changelog(200))
    assert all(c.token_count <= MAX_TOKENS or c.token_count <= HARD_MAX_TOKENS for c in chunks)


def test_ordinals_stay_contiguous_after_merging() -> None:
    """A gap would break the (revision, ordinal) unique constraint on insert."""
    chunks = chunk_document(changelog(30))
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


# --- oversized blocks -----------------------------------------------------


def test_an_oversized_block_is_split_rather_than_stored_whole() -> None:
    """The largest stored chunk reached 24 979 tokens; the provider only read
    its opening, so 94% of it was invisible to search."""
    giant = "## Data\n\n" + "\n".join(f"| row {i} | value {i} |" for i in range(4000))
    chunks = chunk_document(giant)

    assert len(chunks) > 1
    assert all(c.token_count <= HARD_MAX_TOKENS * 1.1 for c in chunks)


def test_splitting_preserves_the_heading_path() -> None:
    giant = "## Reference\n\n" + "\n".join(f"- entry {i}" for i in range(3000))
    chunks = chunk_document(giant)
    assert all(c.heading_path == ["Reference"] for c in chunks)


def test_no_content_is_dropped_when_splitting() -> None:
    giant = "## Data\n\n" + "\n".join(f"unique-marker-{i}" for i in range(2000))
    joined = "\n".join(c.text for c in chunk_document(giant))
    for marker in ("unique-marker-0", "unique-marker-1000", "unique-marker-1999"):
        assert marker in joined


def test_a_normal_document_is_unaffected() -> None:
    prose = "\n\n".join(
        "这是一段足够长的中文正文内容，用于验证常规文档的切分不受影响。" * 6 for _ in range(4)
    )
    chunks = chunk_document(prose)
    assert chunks
    assert all(c.token_count <= HARD_MAX_TOKENS for c in chunks)


# --- contextual header ----------------------------------------------------


def test_a_bare_bullet_gains_its_identifying_context() -> None:
    enriched = build_embedding_text(
        body_text="- Authenticate skill registry downloads",
        title="OpenAI Agents Python v0.19.2 发布",
        source_name="OpenAI Agents Python Releases",
        published_at=datetime(2026, 8, 3, 12, 0),
        heading_path=["Security Fixes"],
    )
    assert "OpenAI Agents Python v0.19.2" in enriched
    assert "2026-08-03" in enriched
    assert "Security Fixes" in enriched
    assert "- Authenticate skill registry downloads" in enriched


def test_the_passage_survives_verbatim() -> None:
    """rag_citation quotes chunk text as evidence; the header must not become
    part of what we claim the source said."""
    body = "模型在 HumanEval+ 上达到 93.29% 的得分。"
    enriched = build_embedding_text(body_text=body, title="标题", source_name="来源")
    assert enriched.endswith(body)


def test_only_the_deepest_headings_are_kept() -> None:
    enriched = build_embedding_text(
        body_text="passage",
        heading_path=["A", "B", "C", "D", "E"],
    )
    assert "E" in enriched
    assert "A" not in enriched.split("\n\n")[0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"title": None, "source_name": None},
        {"heading_path": []},
        {"heading_path": ["", "  "]},
    ],
)
def test_missing_context_yields_the_passage_alone(kwargs: dict) -> None:
    """An item without a title must still be embedded, not skipped."""
    assert build_embedding_text(body_text="passage", **kwargs) == "passage"


def test_header_stays_small_relative_to_the_passage() -> None:
    """Every token in the header is one not spent on the passage."""
    body = "x" * 2000
    enriched = build_embedding_text(
        body_text=body,
        title="T" * 500,
        source_name="S" * 100,
        heading_path=["H" * 100] * 6,
    )
    header = enriched.split("\n\n")[0]
    assert estimate_tokens(header) < estimate_tokens(body)
    assert len(header.split(" › ")) <= MAX_HEADING_SEGMENTS


# --- sibling-section merging ----------------------------------------------


def test_sibling_sections_merge_when_both_are_short() -> None:
    """Release notes give every category its own heading, so requiring an exact
    path match left 861 fragments unmerged — it blocked exactly the documents
    that needed merging most."""
    document = (
        "## Changelog\n\n"
        "### Patch Changes\n\n- one small fix\n\n"
        "### Minor Changes\n\n- another small change\n"
    )
    chunks = chunk_document(document)
    assert len(chunks) == 1
    assert chunks[0].heading_path == ["Changelog"]


def test_top_level_sections_never_merge() -> None:
    """Combining "Installation" with "Breaking Changes" yields a chunk that
    answers neither question."""
    document = "## Installation\n\n- pip install x\n\n## Breaking Changes\n\n- removed y\n"
    chunks = chunk_document(document)
    assert len(chunks) == 2


def test_a_long_sibling_is_not_absorbed() -> None:
    """Only undersized chunks fold; a substantial section keeps its own entry."""
    long_body = "\n".join(f"- detailed entry number {i} with explanation" for i in range(60))
    document = f"## Changelog\n\n### Patch Changes\n\n- tiny\n\n### Major Changes\n\n{long_body}\n"
    assert len(chunk_document(document)) > 1

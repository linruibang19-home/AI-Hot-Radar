"""Topic display metadata drawn from the taxonomy config.

The topic map renders names, descriptions and grouping straight from
`config/taxonomy.yaml`. These tests guard the two ways that goes wrong in
practice: a topic added to the vocabulary but never given a display entry, and a
display entry whose slug does not exist in the vocabulary at all (a typo that
would otherwise vanish silently).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ahr.processing.topics import (
    display_name,
    known_slugs,
    load_display,
    load_taxonomy,
)


def _find_taxonomy() -> Path:
    """Locate config/taxonomy.yaml from either a repo checkout or the image.

    Tests run both ways — `cd apps/ai-service && pytest` puts the repo root three
    levels up, while the container has the file at /app/config — so the path is
    searched rather than assumed.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "taxonomy.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/taxonomy.yaml not found above the test directory")


TAXONOMY_PATH = _find_taxonomy()


@pytest.fixture(scope="module")
def taxonomy() -> dict[str, list[str]]:
    return load_taxonomy(TAXONOMY_PATH)


@pytest.fixture(scope="module")
def display() -> dict[str, dict[str, object]]:
    return load_display(TAXONOMY_PATH)


def test_every_group_has_a_label(taxonomy, display) -> None:
    for parent in taxonomy:
        entry = display["groups"].get(parent)
        assert entry, f"group {parent} has no display entry"
        assert entry.get("label"), f"group {parent} has no label"


def test_every_topic_has_a_name_and_description(taxonomy, display) -> None:
    """A slug shown as 'Llm' on the site means this entry is missing."""
    for children in taxonomy.values():
        for slug in children:
            entry = display["topics"].get(slug)
            assert entry, f"topic {slug} has no display entry"
            assert entry.get("name"), f"topic {slug} has no name"
            assert entry.get("description"), f"topic {slug} has no description"


def test_display_entries_reference_real_topics(taxonomy, display) -> None:
    """A typo'd slug here would produce a display entry nothing ever reads."""
    vocabulary = known_slugs(taxonomy)
    unknown = set(display["topics"]) - vocabulary
    assert not unknown, f"display metadata for unknown topics: {sorted(unknown)}"


def test_group_orders_are_unique(display) -> None:
    """Duplicate orders make the map's section order depend on dict iteration."""
    orders = [entry.get("order") for entry in display["groups"].values()]
    assert len(orders) == len(set(orders))


def test_display_name_falls_back_to_titlecased_slug() -> None:
    """A topic without display metadata must still render, not disappear."""
    assert display_name("brand_new_topic", {"groups": {}, "topics": {}}) == "Brand New Topic"


def test_display_name_prefers_configured_name() -> None:
    meta = {"groups": {}, "topics": {"llm": {"name": "大语言模型"}}}
    assert display_name("llm", meta) == "大语言模型"


def test_missing_display_section_is_tolerated(tmp_path: Path) -> None:
    """`topics` alone must remain sufficient to seed the vocabulary."""
    minimal = tmp_path / "taxonomy.yaml"
    minimal.write_text("topics:\n  models: [llm]\n", encoding="utf-8")

    meta = load_display(minimal)
    assert meta == {"groups": {}, "topics": {}}
    assert display_name("llm", meta) == "Llm"

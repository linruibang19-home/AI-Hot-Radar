"""What a cursor is allowed to call "seen".

The pipeline's comment has always said "only content that actually committed is
treated as seen". It was implemented as `isinstance(adapter, HtmlListingAdapter)`
and so held for one adapter out of seven. `docs_changelog` also carries a
seen-set, and failed it: `discover` returns every section it parsed, the loop
ingests `batch.items[:max_documents]`, and the cursor was saved with all of the
hashes. Sections that were never fetched went behind the cursor permanently and
every later poll was a SUCCESS that discovered nothing.
"""

from __future__ import annotations

import inspect

from ahr.ingestion.adapters.changelog import DocsChangelogAdapter
from ahr.ingestion.adapters.listing import HtmlListingAdapter
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceCursor


def _section(external_id: str, digest: str) -> DiscoveredDocument:
    return DiscoveredDocument(
        external_id=external_id,
        candidate_url=f"https://example.com/changelog#{external_id}",
        title_hint=external_id,
        body_markdown="正文",
        requires_fetch=False,
        attributes={"section_hash": digest},
    )


def _batch(items: list[DiscoveredDocument], hashes: list[str]) -> DiscoveryBatch:
    return DiscoveryBatch(
        items=items,
        next_cursor=SourceCursor(extra={"page_hash": "p", "section_hashes": hashes}),
        http_status=200,
    )


# --- the rule the pipeline asks of every adapter --------------------------


def test_the_pipeline_asks_the_adapter_rather_than_checking_its_class() -> None:
    """An `isinstance` branch is how this drifted: the rule was written once and
    applied to whichever adapter the author had in mind that day."""
    from ahr.ingestion import pipeline

    source = inspect.getsource(pipeline.ingest_source)
    assert 'getattr(adapter, "cursor_for_committed", None)' in source
    # Comments stripped: the comment above the fix names the branch it replaced,
    # and matching against it would fail on the explanation rather than the code.
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "isinstance(adapter, HtmlListingAdapter)" not in code


# --- docs_changelog -------------------------------------------------------


def test_a_section_that_was_not_stored_stays_offerable() -> None:
    """DeepSeek's changelog parsed 21 sections, stored one, and buried twenty."""
    adapter = DocsChangelogAdapter(fetcher=None)
    items = [_section("a", "hash-a"), _section("b", "hash-b"), _section("c", "hash-c")]
    batch = _batch(items, ["hash-a", "hash-b", "hash-c"])

    cursor = adapter.cursor_for_committed(
        batch.next_cursor, batch=batch, committed=["a"], previous=SourceCursor()
    )

    assert cursor.extra["section_hashes"] == ["hash-a"]


def test_sections_seen_on_an_earlier_run_stay_seen() -> None:
    """Otherwise a page whose entries were all ingested long ago would be
    re-offered on every poll, and the changelog would churn forever."""
    adapter = DocsChangelogAdapter(fetcher=None)
    batch = _batch([_section("c", "hash-c")], ["hash-a", "hash-b", "hash-c"])

    cursor = adapter.cursor_for_committed(
        batch.next_cursor,
        batch=batch,
        committed=["c"],
        previous=SourceCursor(extra={"section_hashes": ["hash-a", "hash-b"]}),
    )

    assert set(cursor.extra["section_hashes"]) == {"hash-a", "hash-b", "hash-c"}


def test_a_run_that_stored_nothing_advances_nothing() -> None:
    """Every item failing — which is what the duplicate-URL bug did — must leave
    the work exactly where it was."""
    adapter = DocsChangelogAdapter(fetcher=None)
    batch = _batch([_section("a", "hash-a")], ["hash-a"])

    cursor = adapter.cursor_for_committed(
        batch.next_cursor, batch=batch, committed=[], previous=SourceCursor()
    )

    assert cursor.extra["section_hashes"] == []


def test_the_page_hash_survives_narrowing() -> None:
    """Only the seen-set is rebuilt; the rest of the cursor is the adapter's."""
    adapter = DocsChangelogAdapter(fetcher=None)
    batch = _batch([_section("a", "hash-a")], ["hash-a"])

    cursor = adapter.cursor_for_committed(
        batch.next_cursor, batch=batch, committed=["a"], previous=None
    )

    assert cursor.extra["page_hash"] == "p"


# --- html listing: same rule, unchanged behaviour -------------------------


def test_the_listing_adapter_keeps_committed_ids_and_history() -> None:
    adapter = HtmlListingAdapter(fetcher=None)
    batch = DiscoveryBatch(
        items=[],
        next_cursor=SourceCursor(extra={"seen_ids": ["new-1", "new-2"]}),
        http_status=200,
    )

    cursor = adapter.cursor_for_committed(
        batch.next_cursor,
        batch=batch,
        committed=["new-1"],
        previous=SourceCursor(extra={"seen_ids": ["old-1"]}),
    )

    assert cursor.extra["seen_ids"] == ["new-1", "old-1"]

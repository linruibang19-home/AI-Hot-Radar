"""URL canonicalization tests (AHR-DATA-300 §5, AHR-INGEST-1000 §11)."""

from __future__ import annotations

import pytest

from ahr.ingestion.urls import canonicalize_url, content_hash, url_hash


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.COM/a", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com/a#section", "https://example.com/a"),
        ("https://example.com/a/", "https://example.com/a"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/a?utm_source=x&utm_medium=y", "https://example.com/a"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
    ],
)
def test_canonicalization(raw: str, expected: str) -> None:
    assert canonicalize_url(raw) == expected


def test_business_query_params_are_preserved() -> None:
    """Only known tracking params may be dropped; `?p=` identifies the post."""
    assert (
        canonicalize_url("https://example.com/?p=123&utm_source=x") == "https://example.com/?p=123"
    )


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "not a url", "ftp://example.com/x", "javascript:alert(1)", "file:///etc/passwd"],
)
def test_invalid_urls_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_url(bad)


def test_url_hash_ignores_tracking_params() -> None:
    assert url_hash("https://example.com/a?utm_source=z") == url_hash("https://example.com/a")


def test_content_hash_ignores_whitespace_reflow() -> None:
    assert content_hash("hello   world\n\nagain") == content_hash("hello world again")


def test_content_hash_detects_real_change() -> None:
    assert content_hash("hello world") != content_hash("hello worlds")


# --- Fragments as identity (2026-08-30) -----------------------------------
#
# Dropping the fragment is right for articles and wrong for a changelog, where
# every entry is a section of one page and the `#anchor` is the only thing
# telling them apart. With it dropped they all hashed the same and the unique
# index on `canonical_url_hash` rejected every one after the first — silently,
# because the run still reported SUCCESS with the true section count discovered.
# All twelve `docs_changelog` sources sat at exactly one item; the cursors said
# 406 sections had been seen.


def test_the_fragment_is_dropped_by_default() -> None:
    """Unchanged for articles: a fragment does not identify a distinct
    server-side document, and this is the overwhelmingly common case."""
    assert canonicalize_url("https://example.com/a#section") == "https://example.com/a"


def test_the_fragment_is_kept_when_it_is_the_document() -> None:
    assert (
        canonicalize_url("https://example.com/changelog#v2", keep_fragment=True)
        == "https://example.com/changelog#v2"
    )


def test_changelog_sections_hash_apart_only_with_the_fragment() -> None:
    """The exact failure: two entries of one changelog page."""
    one = "https://docs.example.com/updates#2026-08-26-glm-5-3-flash"
    two = "https://docs.example.com/updates#2026-06-16-glm-5-2"

    assert url_hash(one) == url_hash(two)
    assert url_hash(one, keep_fragment=True) != url_hash(two, keep_fragment=True)


def test_only_the_changelog_profile_keeps_fragments() -> None:
    """Scoped at the one call site that persists, so the general rule stays
    general. Widening it would make `?utm=` sibling links look like documents."""
    import inspect

    from ahr.ingestion import repository

    source = inspect.getsource(repository.persist_document)
    assert 'keep_fragment = source.profile == "docs_changelog"' in source

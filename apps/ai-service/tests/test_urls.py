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

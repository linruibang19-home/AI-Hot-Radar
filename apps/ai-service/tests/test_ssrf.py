"""SSRF guard tests (AHR-QSO-700 §3).

These run offline: every blocked case either fails scheme validation or
resolves to a literal address, so no DNS lookup of an external name is needed.
"""

from __future__ import annotations

import socket

import pytest

from ahr.ingestion.errors import SsrfBlockedError, TransientError
from ahr.ingestion.ssrf import resolve_and_validate


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://10.0.0.1/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        # Cloud metadata endpoint (link-local).
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/x",
        "http://[::1]/x",
    ],
)
def test_private_and_metadata_addresses_are_blocked(url: str) -> None:
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate(url, allow_http=True)


@pytest.mark.parametrize(
    "url", ["ftp://example.com/x", "file:///etc/passwd", "gopher://example.com"]
)
def test_non_http_schemes_are_blocked(url: str) -> None:
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate(url, allow_http=True)


def test_http_is_rejected_unless_explicitly_allowed() -> None:
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate("http://127.0.0.1/x")


def test_url_without_host_is_blocked() -> None:
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate("https:///nohost", allow_http=True)


def test_dns_failure_is_transient_not_a_policy_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed lookup must stay retryable.

    SsrfBlockedError is terminal, so classifying a DNS hiccup as one quarantined
    ten healthy first-party sources (api.github.com, arxiv.org and others) after
    a single failure. Nothing was contacted, so the guard has no finding to make.
    """

    def boom(*args: object, **kwargs: object) -> None:
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", boom)

    with pytest.raises(TransientError) as caught:
        resolve_and_validate("https://api.github.com/repos/x/y/releases")

    assert caught.value.retryable is True
    assert not isinstance(caught.value, SsrfBlockedError)


def test_blocked_address_is_still_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must not have been loosened: a real hit stays non-retryable."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("169.254.169.254", 443))],
    )

    with pytest.raises(SsrfBlockedError) as caught:
        resolve_and_validate("https://metadata.example.com/")

    assert caught.value.retryable is False

"""Offline test harness.

AHR-QSO-700 §1 requires CI to replay fixtures rather than contact live sites.
`fake_fetcher` builds an HttpFetcher backed by a scripted transport, so adapter
behaviour (304, pagination, malformed entries, rate limits) is exercised
deterministically.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from ahr.ingestion.http import HttpConfig, HttpFetcher

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bytes() -> Callable[[str], bytes]:
    def _load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()

    return _load


@pytest.fixture
def make_fetcher() -> Callable[[Callable[[httpx.Request], httpx.Response]], HttpFetcher]:
    """Build a fetcher whose transport is a caller-supplied handler.

    The SSRF validator is replaced with a no-op so the suite performs no DNS
    and passes with the network disabled, as AHR-QSO-700 §1 requires. The real
    resolver-backed guard is covered directly by test_ssrf.py.
    """

    def _make(handler: Callable[[httpx.Request], httpx.Response]) -> HttpFetcher:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        )
        return HttpFetcher(
            HttpConfig(attempts=1),
            client=client,
            validate_target=lambda url, allow_http: None,
        )

    return _make

"""URL canonicalization and content hashing.

AHR-DATA-300 §5 fixes the normalization order:

    parse -> lowercase host -> drop default port -> normalize path
    -> drop fragment -> drop tracking params -> site canonical rule
    -> read page canonical -> compute url_hash

AHR-INGEST-1000 §11 adds the constraint that only *known* tracking parameters
may be removed. Dropping arbitrary query strings would break sources whose
article identity lives in the query (for example `?p=123` on WordPress).
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Analytics/campaign parameters carry no article identity. Everything not on
# this list is preserved.
TRACKING_PARAM_PREFIXES = ("utm_",)

TRACKING_PARAMS = frozenset(
    {
        "ref",
        "referrer",
        "source",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "spm",
        "scm",
        "from",
        "share_source",
    }
)

DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PARAM_PREFIXES)


def canonicalize_url(url: str) -> str:
    """Return a stable form of `url` for identity comparison.

    Raises ValueError when the input is not an absolute http(s) URL, so callers
    fail loudly rather than silently hashing garbage.
    """
    if not url or not url.strip():
        raise ValueError("empty url")

    parts = urlsplit(url.strip())

    if parts.scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {parts.scheme or '(none)'}")
    if not parts.hostname:
        raise ValueError("url has no host")

    host = parts.hostname.lower()
    port = parts.port
    netloc = host if port is None or DEFAULT_PORTS.get(parts.scheme) == port else f"{host}:{port}"

    path = parts.path or "/"
    # A trailing slash is not a distinct document, except at the site root.
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    ]
    query = urlencode(sorted(kept))

    # Fragments never identify a distinct server-side document.
    return urlunsplit((parts.scheme, netloc, path, query, ""))


def url_hash(url: str) -> str:
    """SHA-256 of the canonical form, used as `canonical_url_hash`."""
    return hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    """SHA-256 of extracted body text, used as `content_sha256`.

    Whitespace is collapsed so that cosmetic reformatting of the same article
    does not present as new content.
    """
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

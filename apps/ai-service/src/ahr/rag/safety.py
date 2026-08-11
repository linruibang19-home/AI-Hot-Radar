"""Deterministic publication safety checks for the public RAG endpoint.

This is intentionally narrow. It is a last boundary for credential-shaped
output, not a claim that regexes are a complete DLP product. The detector only
returns labels; callers must never log the matched value.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    ),
    ("authorization_header", re.compile(r"\bAuthorization\s*:\s*Bearer\s+\S+", re.I)),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


def credential_labels(text: str) -> tuple[str, ...]:
    """Return credential kinds without retaining or exposing the secret."""
    return tuple(label for label, pattern in _SECRET_PATTERNS if pattern.search(text))

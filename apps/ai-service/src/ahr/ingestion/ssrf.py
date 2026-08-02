"""SSRF protection for outbound fetches.

AHR-QSO-700 §3 requires: http/https only, DNS resolved before connecting, and
private, loopback and cloud metadata addresses rejected — re-checked on every
redirect hop, because a public host may redirect to 169.254.169.254.

Checking the hostname string alone is not sufficient: an attacker controls DNS
for their own domain and can point it at a private address.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from ahr.ingestion.errors import SsrfBlockedError, TransientError

ALLOWED_SCHEMES = frozenset({"https", "http"})


# Link-local addresses cover the cloud metadata endpoints (169.254.169.254 on
# AWS/GCP/Azure), so no separate allow/deny list is needed for those.
def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_and_validate(url: str, *, allow_http: bool = False) -> list[str]:
    """Resolve `url`'s host and reject it if any address is non-public.

    Returns the resolved addresses so the caller can log what was contacted.
    Every address is checked: a host with both a public A record and a private
    AAAA record must not slip through.
    """
    parts = urlsplit(url)

    allowed = ALLOWED_SCHEMES if allow_http else frozenset({"https"})
    if parts.scheme not in allowed:
        raise SsrfBlockedError(f"scheme not allowed: {parts.scheme or '(none)'}")

    host = parts.hostname
    if not host:
        raise SsrfBlockedError("url has no host")

    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        # Transient, not a policy block. A failed lookup means nothing was
        # contacted, so the guard has made no security finding — and
        # SsrfBlockedError is not retryable, so classifying it that way let a
        # momentary DNS hiccup permanently quarantine first-party sources
        # (api.github.com, arxiv.org and eight others were lost this way).
        raise TransientError(f"dns resolution failed for {host}: {exc}") from exc

    addresses: list[str] = []
    for info in infos:
        # sockaddr is (host, port) for IPv4 and (host, port, flow, scope) for
        # IPv6; the host element is always the string address.
        address = str(info[4][0])
        if address in addresses:
            continue
        addresses.append(address)
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise SsrfBlockedError(f"unparseable address {address} for {host}") from exc
        if _is_blocked_address(parsed):
            raise SsrfBlockedError(f"{host} resolves to non-public address {address}")

    if not addresses:
        raise SsrfBlockedError(f"no addresses for {host}")

    return addresses

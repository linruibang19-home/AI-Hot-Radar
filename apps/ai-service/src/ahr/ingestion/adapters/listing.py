"""HTML listing adapter.

AHR-INGEST-1000 §6 discovery priority:

    JSON-LD ItemList/BlogPosting -> same-site article links -> site selector

Only candidate URLs are produced here; the body always comes from a follow-up
fetch of the article page, so a listing teaser can never become body text.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlsplit

from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceConfig, SourceCursor
from ahr.ingestion.urls import canonicalize_url, url_hash

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_HREF_RE = re.compile(
    r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_SITEMAP_URL_RE = re.compile(r"<url\b[^>]*>(.*?)</url>", re.IGNORECASE | re.DOTALL)
_SITEMAP_LOC_RE = re.compile(r"<loc\b[^>]*>(.*?)</loc>", re.IGNORECASE | re.DOTALL)
_SITEMAP_LASTMOD_RE = re.compile(r"<lastmod\b[^>]*>(.*?)</lastmod>", re.IGNORECASE | re.DOTALL)

# Listing pages link to far more than articles; these paths are navigation.
_NON_ARTICLE_HINTS = (
    "/tag/",
    "/tags/",
    "/category/",
    "/categories/",
    "/author/",
    "/page/",
    "/search",
    "/login",
    "/signup",
    "/pricing",
    "/careers",
    "/contact",
    "/privacy",
    "/terms",
    "/rss",
    "/feed",
    "/about",
)

_SITEMAP_ARTICLE_PATHS = (
    "/article/",
    "/articles/",
    "/blog/",
    "/news/",
    "/posts/",
)

# Some curated team/blog listings live in a navigation subtree while their
# article pages use a site-wide numeric route.  Dynamic listings may opt into
# these two bounded shapes; this is deliberately not a generic "same host"
# escape hatch because that would turn navigation, products and courses into
# article candidates.
_CROSS_PATH_ARTICLE_RE = re.compile(r"^/(?:article/\d+|developer/article/\d+)/?$")


def _collect_jsonld_urls(html: str, base_url: str) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_type = str(node.get("@type", ""))
            if node_type in ("BlogPosting", "NewsArticle", "Article", "TechArticle"):
                url = node.get("url") or node.get("mainEntityOfPage")
                if isinstance(url, dict):
                    url = url.get("@id")
                if isinstance(url, str):
                    found.append((urljoin(base_url, url), node.get("headline")))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for block in _JSONLD_RE.findall(html):
        try:
            walk(json.loads(block.strip()))
        except json.JSONDecodeError:
            continue
    return found


def _looks_like_article(
    path: str, listing_path: str, *, allow_cross_path_articles: bool = False
) -> bool:
    if any(hint in path for hint in _NON_ARTICLE_HINTS):
        return False
    if path.rstrip("/") == listing_path.rstrip("/"):
        return False
    if allow_cross_path_articles:
        return bool(_CROSS_PATH_ARTICLE_RE.fullmatch(path))
    # An article lives below the listing, e.g. /blog/ -> /blog/my-post.
    if listing_path.rstrip("/") and not path.startswith(listing_path.rstrip("/")):
        return False
    remainder = path[len(listing_path.rstrip("/")) :].strip("/")
    return bool(remainder) and len(remainder) > 3


def _collect_link_urls(
    html: str, base_url: str, *, allow_cross_path_articles: bool = False
) -> list[tuple[str, str | None]]:
    base = urlsplit(base_url)
    listing_path = base.path or "/"
    found: list[tuple[str, str | None]] = []

    for match in _HREF_RE.finditer(html):
        href = match.group(1).strip()
        if href.startswith(("#", "mailto:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or parts.netloc != base.netloc:
            continue
        if not _looks_like_article(
            parts.path,
            listing_path,
            allow_cross_path_articles=allow_cross_path_articles,
        ):
            continue
        title = _TAG_RE.sub("", match.group(2)).strip() or None
        found.append((absolute, title))
    return found


def _parse_lastmod(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _looks_like_sitemap_article(path: str) -> bool:
    """Keep document URLs and reject sitemap navigation/taxonomy entries.

    A sitemap is not scoped below its own URL path, so the listing-page rule
    cannot be reused. These shapes cover the registry's article-like sources;
    a new shape still needs a fixture before activation.
    """
    lowered = path.lower()
    if any(hint in lowered for hint in _NON_ARTICLE_HINTS):
        return False
    if any(hint in lowered for hint in _SITEMAP_ARTICLE_PATHS):
        return bool(lowered.rstrip("/").split("/")[-1])
    return bool(re.fullmatch(r"/p/\d+\.html", lowered))


def _collect_sitemap_urls(xml: str, base_url: str) -> list[tuple[str, str | None]]:
    """Extract newest article URLs from a sitemap ``urlset``.

    ``lastmod`` is used only for ordering. It is modification time, not a
    trustworthy publication timestamp, so it never populates published_at.
    """
    base_host = urlsplit(base_url).netloc.lower()
    found: list[tuple[str, datetime | None]] = []
    for block in _SITEMAP_URL_RE.findall(xml):
        loc_match = _SITEMAP_LOC_RE.search(block)
        if not loc_match:
            continue
        raw_url = unescape(_TAG_RE.sub("", loc_match.group(1))).strip()
        parts = urlsplit(raw_url)
        if parts.scheme != "https" or parts.netloc.lower() != base_host:
            continue
        if not _looks_like_sitemap_article(parts.path):
            continue
        lastmod_match = _SITEMAP_LASTMOD_RE.search(block)
        lastmod = _parse_lastmod(lastmod_match.group(1) if lastmod_match else None)
        found.append((raw_url, lastmod))

    # Unknown lastmod sorts last, while equal/absent dates retain source order.
    found.sort(
        key=lambda item: item[1].timestamp() if item[1] is not None else float("-inf"),
        reverse=True,
    )
    return [(url, None) for url, _ in found]


class HtmlListingAdapter:
    """Discovers article URLs from a listing page."""

    name = "static_listing_to_article"

    def __init__(self, fetcher: Any, *, max_items: int = 30) -> None:
        self._fetcher = fetcher
        self._max_items = max_items

    async def discover(
        self, source: SourceConfig, cursor: SourceCursor | None = None
    ) -> DiscoveryBatch:
        if not source.discovery_url:
            raise ParseFailedError(f"source {source.id} has no discovery_url")

        cursor = cursor or SourceCursor()
        response = await self._fetcher.fetch(
            source.discovery_url, etag=cursor.etag, last_modified=cursor.last_modified
        )
        if response.not_modified:
            return DiscoveryBatch.unchanged(cursor)

        html = response.text()
        if "<urlset" in html.lower():
            candidates = _collect_sitemap_urls(html, response.final_url)
            discovery_method = "sitemap"
        else:
            candidates = _collect_jsonld_urls(html, response.final_url)
            discovery_method = "json_ld"
        if not candidates:
            candidates = _collect_link_urls(
                html,
                response.final_url,
                allow_cross_path_articles=source.profile == "dynamic_listing_to_article",
            )
            discovery_method = "same_site_links"

        # A listing adapter is a live-update window, not an implicit historical
        # backfill job. Bound the candidate window before applying the cursor so
        # an activation cannot walk thousands of old sitemap entries every two
        # minutes and unexpectedly spend enrichment budget.
        candidates = candidates[: self._max_items]

        seen_ids = set((cursor.extra or {}).get("seen_ids", []))
        items: list[DiscoveredDocument] = []
        collected: list[str] = []

        for raw_url, title in candidates:
            try:
                canonical = canonicalize_url(raw_url)
            except ValueError:
                continue
            external_id = url_hash(canonical)
            if external_id in {item.external_id for item in items}:
                continue
            collected.append(external_id)
            if external_id in seen_ids:
                continue

            items.append(
                DiscoveredDocument(
                    external_id=external_id,
                    candidate_url=canonical,
                    title_hint=title,
                    # The listing carries no trustworthy body; fetch the article.
                    requires_fetch=True,
                    attributes={"discovery_method": discovery_method},
                )
            )
            if len(items) >= self._max_items:
                break

        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(
                etag=response.etag,
                last_modified=response.last_modified,
                newest_entry_time=cursor.newest_entry_time,
                extra={"seen_ids": (collected + list(seen_ids))[:400]},
            ),
            http_status=response.status_code,
            empty_reason=None if items else ("NO_NEW_ARTICLES" if candidates else "NO_LINKS_FOUND"),
        )

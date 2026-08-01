"""Article fulltext acquisition.

AHR-INGEST-1000 §6 fixes the extractor chain:

    JSON-LD articleBody -> Trafilatura -> Readability -> site selector

and the canonical resolution order: `link rel=canonical` -> `og:url` ->
final response URL. Trafilatura already implements JSON-LD and readability-style
extraction internally, so it is the primary extractor here; a declarative
site selector remains the documented next fallback (site-overrides.yaml, M1-002).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import trafilatura

from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.fulltext_gate import ExtractedDocument
from ahr.ingestion.http import FetchResult
from ahr.ingestion.urls import canonicalize_url

_CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', re.IGNORECASE
)
_OG_URL_RE = re.compile(
    r'<meta[^>]+property=["\']og:url["\'][^>]*content=["\']([^"\']+)["\']', re.IGNORECASE
)
_LINK_TEXT_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ArticleExtraction:
    document: ExtractedDocument
    body_markdown: str | None
    raw_html: str


def resolve_canonical(html: str, final_url: str) -> str:
    """Pick the canonical URL, falling back to the final response URL."""
    for pattern in (_CANONICAL_RE, _OG_URL_RE):
        match = pattern.search(html)
        if match:
            candidate = match.group(1).strip()
            try:
                # Site-declared canonicals are sometimes relative or malformed;
                # an unusable value must not lose the known-good final URL.
                return canonicalize_url(candidate)
            except ValueError:
                continue
    return canonicalize_url(final_url)


_ARTICLE_REGION_RE = re.compile(
    r"<(article|main)\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL
)


def _link_text_chars(html: str) -> int:
    """Visible characters inside anchors within the article region.

    Measuring across the whole page would count navigation, sidebar and footer
    links against the extracted body, inflating density far above the 0.35
    threshold and rejecting perfectly good articles. Scope to <article>/<main>
    when present; otherwise fall back to the whole document, which is the
    conservative reading for pages with no semantic wrapper.
    """
    region = html
    match = _ARTICLE_REGION_RE.search(html)
    if match:
        region = match.group(2)

    total = 0
    for link in _LINK_TEXT_RE.finditer(region):
        total += len(_TAG_RE.sub("", link.group(1)).strip())
    return total


def _published_from_jsonld(html: str) -> datetime | None:
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for key in ("datePublished", "dateCreated", "uploadDate"):
                value = candidate.get(key)
                if isinstance(value, str):
                    try:
                        return datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        continue
    return None


def extract_article(
    response: FetchResult,
    *,
    source_id: str,
    title_hint: str | None = None,
    published_hint: datetime | None = None,
) -> ArticleExtraction:
    """Extract body text and metadata from a fetched article page."""
    html = response.text()
    if not html.strip():
        raise ParseFailedError(f"empty response body from {response.final_url}")

    body_text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    body_markdown = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        output_format="markdown",
    )

    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title if metadata else None) or title_hint

    published = published_hint or _published_from_jsonld(html)
    if published is None and metadata and metadata.date:
        try:
            published = datetime.fromisoformat(str(metadata.date)).replace(tzinfo=UTC)
        except ValueError:
            published = None

    canonical = resolve_canonical(html, response.final_url)

    document = ExtractedDocument(
        body_text=body_text or "",
        title=title,
        canonical_url=canonical,
        published_at=published,
        source_id=source_id,
        link_text_chars=_link_text_chars(html),
        extractor="trafilatura",
    )
    return ArticleExtraction(document=document, body_markdown=body_markdown, raw_html=html)

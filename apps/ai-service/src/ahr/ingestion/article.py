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


def _link_text_chars(body_markdown: str | None) -> int:
    """Visible characters inside links within the *extracted* body.

    Earlier attempts measured anchors in the raw HTML — first across the whole
    page, then within <article>/<main>. Both overcount badly: Cloudflare's blog
    nests the article inside a <main> that also holds navigation and related
    posts, giving a 397k-character "article region" and a density of 0.92 for a
    perfectly good post.

    Measuring the extracted body instead compares like with like: the numerator
    and denominator now describe the same text. Trafilatura's markdown output
    represents links as [text](url), so link text is recoverable from it.
    """
    if not body_markdown:
        return 0
    return sum(len(match.group(1)) for match in _MD_LINK_RE.finditer(body_markdown))


_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


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
        link_text_chars=_link_text_chars(body_markdown),
        extractor="trafilatura",
    )
    return ArticleExtraction(document=document, body_markdown=body_markdown, raw_html=html)

"""arXiv paper adapter.

AHR-INGEST-1000 §8: RSS discovers papers, then `/html/{id}` is preferred for
fulltext with `/pdf/{id}` as the fallback. The RSS summary is the abstract and
is stored as such — never as the paper body.

arXiv publishes on weekdays only (`<skipDays>Saturday Sunday</skipDays>`), so an
empty feed at the weekend is expected and must not be scored as a failure.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

import feedparser
import pymupdf

from ahr.ingestion.adapters.rss import _entry_time, _entry_url
from ahr.ingestion.article import ArticleExtraction, extract_article
from ahr.ingestion.errors import NotFoundError, ParseFailedError
from ahr.ingestion.fulltext_gate import Decision, ExtractedDocument, evaluate
from ahr.ingestion.http import FetchResult
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceConfig, SourceCursor

RSS_ROOT = "https://rss.arxiv.org/rss"
ABS_ROOT = "https://arxiv.org/abs"
HTML_ROOT = "https://arxiv.org/html"
PDF_ROOT = "https://arxiv.org/pdf"

# Matches 2401.12345v2 and the pre-2007 form cs/0701001.
_ARXIV_ID_RE = re.compile(r"(?:abs|html|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?|[a-z-]+/[0-9]{7})")

# arXiv asks for roughly one request every three seconds.
DEFAULT_RATE_LIMIT_SECONDS = 3.0
MAX_PDF_PAGES = 200
MAX_PDF_TEXT_CHARS = 2_000_000


@dataclass(frozen=True)
class PaperAcquisition:
    """The actual fulltext response and its normalized paper extraction."""

    response: FetchResult
    extraction: ArticleExtraction
    requested_url: str


def extract_arxiv_id(url: str) -> str | None:
    match = _ARXIV_ID_RE.search(url)
    return match.group(1) if match else None


_SKIP_DAY_RE = re.compile(r"<day>\s*([A-Za-z]+)\s*</day>", re.IGNORECASE)


def skip_days(feed_body: bytes) -> set[str]:
    """Days on which the publisher declares it does not publish.

    feedparser flattens `<skipDays>` to an empty string rather than exposing the
    nested `<day>` elements, so this reads them from the raw XML.
    """
    text = feed_body.decode("utf-8", errors="replace")
    return {match.group(1).strip().lower() for match in _SKIP_DAY_RE.finditer(text)}


def is_skip_day_now(days: set[str], *, today: str | None = None) -> bool:
    current = today or datetime.now(UTC).strftime("%A").lower()
    return current in days


class ArxivPaperAdapter:
    """Discovers papers for one arXiv subject feed."""

    name = "arxiv_feed_paper"

    def __init__(
        self, fetcher: Any, *, rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS
    ) -> None:
        self._fetcher = fetcher
        self._rate_limit_seconds = max(rate_limit_seconds, 0.0)
        self._last_request_at: float | None = None

    async def _fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        """Fetch one arXiv resource without exceeding the documented host rate."""

        if self._last_request_at is not None and self._rate_limit_seconds:
            remaining = self._rate_limit_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        response = cast(
            "FetchResult",
            await self._fetcher.fetch(url, headers=headers, etag=etag, last_modified=last_modified),
        )
        self._last_request_at = time.monotonic()
        return response

    async def discover(
        self, source: SourceConfig, cursor: SourceCursor | None = None
    ) -> DiscoveryBatch:
        subject = source.subject
        if not subject and source.discovery_url:
            subject = source.discovery_url.rstrip("/").rsplit("/", 1)[-1]
        if not subject:
            raise ParseFailedError(f"source {source.id} has no arXiv subject")

        cursor = cursor or SourceCursor()
        response = await self._fetch(
            f"{RSS_ROOT}/{subject}",
            headers={"Accept": "application/rss+xml, application/xml"},
            etag=cursor.etag,
            last_modified=cursor.last_modified,
        )

        if response.not_modified:
            return DiscoveryBatch.unchanged(cursor)

        feed = feedparser.parse(response.body)
        if feed.bozo and not feed.entries:
            raise ParseFailedError(
                f"failed to parse arXiv feed {subject}: {feed.get('bozo_exception')}"
            )

        items: list[DiscoveredDocument] = []
        newest_seen = cursor.newest_entry_time

        for entry in feed.entries:
            url = _entry_url(entry)
            if not url:
                continue
            arxiv_id = extract_arxiv_id(url) or entry.get("id", "").split("/")[-1]
            if not arxiv_id:
                continue

            published = _entry_time(entry)
            if cursor.newest_entry_time and published and published <= cursor.newest_entry_time:
                continue
            if published and (newest_seen is None or published > newest_seen):
                newest_seen = published

            items.append(
                DiscoveredDocument(
                    external_id=arxiv_id,
                    # Cite the abstract page; HTML/PDF are fulltext sources, not
                    # the canonical reference.
                    candidate_url=f"{ABS_ROOT}/{arxiv_id}",
                    title_hint=entry.get("title"),
                    published_at_hint=published,
                    # The RSS summary is the abstract, not the paper body.
                    discovery_summary=entry.get("summary") or entry.get("description"),
                    requires_fetch=True,
                    attributes={
                        "arxiv_id": arxiv_id,
                        "html_url": f"{HTML_ROOT}/{arxiv_id}",
                        "pdf_url": f"{PDF_ROOT}/{arxiv_id}",
                        "subject": subject,
                    },
                )
            )

        empty_reason = None
        if not items:
            # Distinguish "arXiv does not publish today" from "the source broke".
            if not feed.entries and is_skip_day_now(skip_days(response.body)):
                empty_reason = "PUBLISHER_SKIP_DAY"
            elif feed.entries:
                empty_reason = "NO_NEW_ENTRIES"
            else:
                empty_reason = "FEED_EMPTY"

        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(
                etag=response.etag,
                last_modified=response.last_modified,
                newest_entry_time=newest_seen,
                extra={"subject": subject},
            ),
            http_status=response.status_code,
            empty_reason=empty_reason,
        )

    async def acquire(self, item: DiscoveredDocument, *, source_id: str) -> PaperAcquisition:
        """Fetch paper HTML first and use the PDF only when HTML is unavailable or unusable.

        The abstract page remains the canonical citation target. Its metadata is
        already carried by the RSS entry; it is never mistaken for paper body.
        """

        arxiv_id = str(
            item.attributes.get("arxiv_id") or extract_arxiv_id(item.candidate_url) or ""
        )
        if not arxiv_id:
            raise ParseFailedError(f"cannot derive arXiv id from {item.candidate_url}")

        html_url = str(item.attributes.get("html_url") or f"{HTML_ROOT}/{arxiv_id}")
        try:
            html_response = await self._fetch(html_url, headers={"Accept": "text/html"})
            html = extract_article(
                html_response,
                source_id=source_id,
                title_hint=item.title_hint,
                published_hint=item.published_at_hint,
            )
            html_document = replace(
                html.document,
                canonical_url=item.candidate_url,
                extractor="arxiv_html",
            )
            html = replace(html, document=html_document)
            if evaluate(html_document).decision is Decision.ACCEPTED:
                return PaperAcquisition(html_response, html, html_url)
        except ParseFailedError:
            # A structurally invalid HTML rendition is equivalent to absence;
            # the public PDF is the documented fallback.
            pass
        except NotFoundError:
            # Only a missing HTML rendition falls back. Access restrictions,
            # rate limits and transport failures retain their taxonomy.
            pass

        pdf_url = str(item.attributes.get("pdf_url") or f"{PDF_ROOT}/{arxiv_id}")
        pdf_response = await self._fetch(pdf_url, headers={"Accept": "application/pdf"})
        extraction = _extract_pdf(
            pdf_response,
            source_id=source_id,
            canonical_url=item.candidate_url,
            title=item.title_hint,
            published_at=item.published_at_hint,
        )
        return PaperAcquisition(pdf_response, extraction, pdf_url)


def _extract_pdf(
    response: FetchResult,
    *,
    source_id: str,
    canonical_url: str,
    title: str | None,
    published_at: datetime | None,
) -> ArticleExtraction:
    """Extract bounded page text from an arXiv PDF with page separators."""

    try:
        # PyMuPDF's wheel exposes runtime types inconsistently across releases;
        # isolate that untyped boundary here instead of letting Any spread into
        # the extraction result.
        pdf: Any = cast(Any, pymupdf).open(stream=response.body, filetype="pdf")
    except Exception as exc:
        raise ParseFailedError(f"invalid arXiv PDF from {response.final_url}: {exc}") from exc

    try:
        if pdf.needs_pass:
            raise ParseFailedError(f"encrypted arXiv PDF from {response.final_url}")
        if pdf.page_count > MAX_PDF_PAGES:
            raise ParseFailedError(
                f"arXiv PDF has {pdf.page_count} pages, limit is {MAX_PDF_PAGES}"
            )

        pages: list[str] = []
        total = 0
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text("text", sort=True).strip()
            if not text:
                continue
            total += len(text)
            if total > MAX_PDF_TEXT_CHARS:
                raise ParseFailedError(f"arXiv PDF text exceeds {MAX_PDF_TEXT_CHARS} characters")
            pages.append(f"[Page {page_number}]\n{text}")
    finally:
        pdf.close()

    body = "\n\n".join(pages)
    if not body:
        raise ParseFailedError(f"arXiv PDF contains no extractable text: {response.final_url}")

    document = ExtractedDocument(
        body_text=body,
        title=title,
        canonical_url=canonical_url,
        published_at=published_at,
        source_id=source_id,
        extractor="arxiv_pdf_pymupdf",
    )
    return ArticleExtraction(document=document, body_markdown=body, raw_html="")

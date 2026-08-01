"""Official changelog adapter.

AHR-INGEST-1000 §5: a changelog has no per-entry API. One fixed URL is fetched
conditionally, the main region is converted to text, and it is split on
date/version headings so each section becomes its own document with a stable
hash.

The heading itself supplies the publication date. When no date can be parsed,
`published_at` stays null and only `observed_at` is recorded — the spec forbids
inventing publication dates.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

import trafilatura

from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceConfig, SourceCursor

# trafilatura's XML output marks headings as <head>, preserving the structure
# its markdown output flattens. The Gemini changelog yields 129 dated headings
# as XML versus 1 as markdown, which is the difference between per-release
# documents and one undifferentiated page.
_XML_HEAD_RE = re.compile(r"<head[^>]*>(.*?)</head>", re.DOTALL)
_XML_TAG_RE = re.compile(r"<[^>]+>")

_DATE_PATTERNS = (
    re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"),
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2}),?\s+(\d{4})",
        re.IGNORECASE,
    ),
)

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}


def parse_heading_date(heading: str) -> datetime | None:
    """Extract a publication date from a changelog heading, if one is present."""
    for pattern in _DATE_PATTERNS:
        match = pattern.search(heading)
        if not match:
            continue
        try:
            if pattern is _DATE_PATTERNS[2]:
                month = _MONTHS[match.group(1).lower()]
                return datetime(int(match.group(3)), month, int(match.group(2)), tzinfo=UTC)
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=UTC
            )
        except (ValueError, KeyError):
            continue
    return None


def split_sections(document_xml: str) -> list[tuple[str, str]]:
    """Split trafilatura XML into (heading, body) pairs.

    Content before the first heading is dropped: it is page furniture, not a
    changelog entry.
    """
    matches = list(_XML_HEAD_RE.finditer(document_xml))
    if not matches:
        return []

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        heading = _XML_TAG_RE.sub("", match.group(1)).strip()
        if not heading:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document_xml)
        body = _XML_TAG_RE.sub("\n", document_xml[start:end])
        body = "\n".join(line.strip() for line in body.splitlines() if line.strip())
        if body:
            sections.append((heading, body))
    return sections


class DocsChangelogAdapter:
    """Turns one changelog page into per-section documents."""

    name = "docs_changelog"

    def __init__(self, fetcher: Any) -> None:
        self._fetcher = fetcher

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
        document_xml = trafilatura.extract(
            html, include_comments=False, include_tables=True, output_format="xml"
        )
        if not document_xml:
            raise ParseFailedError(f"no extractable content at {source.discovery_url}")

        page_hash = hashlib.sha256(document_xml.encode("utf-8")).hexdigest()
        seen_hashes = set((cursor.extra or {}).get("section_hashes", []))

        items: list[DiscoveredDocument] = []
        new_hashes: list[str] = []

        for index, (heading, body) in enumerate(split_sections(document_xml)):
            section_hash = hashlib.sha256(f"{heading}\n{body}".encode()).hexdigest()
            new_hashes.append(section_hash)
            if section_hash in seen_hashes:
                continue

            anchor = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:60]
            items.append(
                DiscoveredDocument(
                    # Identity is the heading, not the hash: an edited section
                    # must update the existing item rather than create a new one.
                    external_id=f"{source.id}#{anchor or index}",
                    candidate_url=f"{source.discovery_url}#{anchor}"
                    if anchor
                    else source.discovery_url,
                    title_hint=heading,
                    published_at_hint=parse_heading_date(heading),
                    body_markdown=body,
                    # The section body is already the complete document.
                    requires_fetch=False,
                    attributes={"section_hash": section_hash, "page_hash": page_hash},
                )
            )

        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(
                etag=response.etag,
                last_modified=response.last_modified,
                newest_entry_time=cursor.newest_entry_time,
                # Bounded so the cursor row cannot grow without limit.
                extra={"page_hash": page_hash, "section_hashes": new_hashes[:200]},
            ),
            http_status=response.status_code,
            empty_reason="NO_CHANGED_SECTIONS" if not items else None,
        )

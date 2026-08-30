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
from dataclasses import replace
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


# Docs sites increasingly serve the same page as Markdown for machine readers,
# and there the releases survive as MDX components instead of being flattened
# into prose. Zhipu's 新品发布 page is the case that forced this: as HTML,
# trafilatura returns one section titled 「公告通知」 out of a 2.2MB page, so the
# source produced exactly one item and stayed there. The `.md` twin keeps every
# release as `<Update label="2026-08-26" description="GLM-5.3-Flash …">`, which
# carries the date the HTML rendering loses.
_MDX_UPDATE_RE = re.compile(
    r"<Update\b[^>]*\blabel=\"([^\"]+)\"[^>]*\bdescription=\"([^\"]*)\"[^>]*>(.*?)</Update>",
    re.DOTALL,
)
_MDX_TAG_RE = re.compile(r"</?[A-Z][A-Za-z0-9]*\b[^>]*>")


def split_mdx_updates(markdown: str) -> list[tuple[str, str]]:
    """Split MDX `<Update label=… description=…>` blocks into (heading, body).

    The heading is `label description` so `parse_heading_date` finds the date
    where it already looks, rather than growing a second date path.
    """
    sections: list[tuple[str, str]] = []
    for match in _MDX_UPDATE_RE.finditer(markdown):
        label, description, body = match.group(1), match.group(2), match.group(3)
        heading = f"{label} {description}".strip()
        body = _MDX_TAG_RE.sub("", body)
        body = "\n".join(line.strip() for line in body.splitlines() if line.strip())
        if heading and body:
            sections.append((heading, body))
    return sections


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

        body_text = response.text()
        content_type = (response.headers.get("content-type") or "").lower()
        is_markdown = "markdown" in content_type or source.discovery_url.endswith(".md")

        if is_markdown:
            # Nothing to extract: the response *is* the document.
            document = body_text
            sections = split_mdx_updates(body_text)
        else:
            document = trafilatura.extract(
                body_text, include_comments=False, include_tables=True, output_format="xml"
            )
            if not document:
                raise ParseFailedError(f"no extractable content at {source.discovery_url}")
            sections = split_sections(document)

        page_hash = hashlib.sha256(document.encode("utf-8")).hexdigest()
        seen_hashes = set((cursor.extra or {}).get("section_hashes", []))

        items: list[DiscoveredDocument] = []
        new_hashes: list[str] = []

        for heading, body in sections:
            section_hash = hashlib.sha256(f"{heading}\n{body}".encode()).hexdigest()
            new_hashes.append(section_hash)
            if section_hash in seen_hashes:
                continue

            anchor = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:60]
            # A heading with no ASCII — every Chinese-only one — slugifies to the
            # empty string, and the old fallback was the loop index. That makes
            # identity positional: one release added at the top of the page
            # renumbers every section below it, and the whole changelog
            # re-ingests as new items. Hash the heading instead, so identity
            # tracks the heading exactly as the comment below promises.
            slug = anchor or hashlib.sha256(heading.encode("utf-8")).hexdigest()[:16]
            items.append(
                DiscoveredDocument(
                    # Identity is the heading, not the hash: an edited section
                    # must update the existing item rather than create a new one.
                    external_id=f"{source.id}#{slug}",
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

    def cursor_for_committed(
        self,
        next_cursor: SourceCursor,
        *,
        batch: DiscoveryBatch,
        committed: list[str],
        previous: SourceCursor | None,
    ) -> SourceCursor:
        """Mark as seen only the sections that were actually stored.

        `discover` returns every section on the page; the pipeline ingests
        `batch.items[:max_documents]` — five, by default. Saving all of the
        hashes therefore retired sections that were never fetched. DeepSeek's
        changelog parsed 21 sections, stored one, and buried twenty: every poll
        afterwards was a SUCCESS that discovered nothing, and the source sat
        green in the console with a single item behind it.

        Sections already seen before this run stay seen — they are not new work,
        and re-offering them would make the page churn forever.
        """
        stored = {
            item.attributes.get("section_hash")
            for item in batch.items
            if item.external_id in set(committed)
        }
        seen_before = set((previous.extra or {}).get("section_hashes", [])) if previous else set()
        kept = [
            digest
            for digest in (next_cursor.extra or {}).get("section_hashes", [])
            if digest in stored or digest in seen_before
        ]
        return replace(next_cursor, extra={**(next_cursor.extra or {}), "section_hashes": kept})

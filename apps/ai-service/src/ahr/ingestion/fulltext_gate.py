"""Fulltext quality gate.

AHR-SOURCE-900 §4.1 and the `fulltext_gate` block in
config/ingestion-profiles.yaml define what counts as real article text. The gate
exists to stop three specific failure modes:

1. a feed summary being stored as if it were the article body;
2. a login wall, cookie notice or error page being stored as content;
3. a navigation-heavy page being counted as a successful extraction.

`AHR-SOURCE-900` §8 is explicit that metadata-only results must never be counted
toward the fulltext success rate, so `metadata_only` is a distinct decision
rather than a pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    METADATA_ONLY = "METADATA_ONLY"


@dataclass(frozen=True)
class GateConfig:
    min_body_chars_article: int = 300
    min_body_chars_release: int = 80
    min_paragraphs_article: int = 2
    max_link_density: float = 0.35
    reject_markers: tuple[str, ...] = (
        "enable javascript",
        "sign in to continue",
        "access denied",
        "verify you are human",
    )
    required_metadata_count: int = 3


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    reason_code: str | None
    body_chars: int
    paragraph_count: int
    link_density: float

    @property
    def accepted(self) -> bool:
        return self.decision is Decision.ACCEPTED


@dataclass
class ExtractedDocument:
    body_text: str
    title: str | None = None
    canonical_url: str | None = None
    published_at: object | None = None
    source_id: str | None = None
    link_text_chars: int = 0
    extractor: str = "unknown"


# Extractors disagree on paragraph separators: trafilatura emits single
# newlines, while markdown and raw HTML-to-text conversions emit blank lines.
# Splitting on any newline run counts both correctly; a lone wrapped sentence
# is excluded by the minimum length so soft-wrapped text is not overcounted.
_PARAGRAPH_SPLIT = re.compile(r"\n+")
_MIN_PARAGRAPH_CHARS = 40


def _paragraph_count(text: str) -> int:
    return sum(
        1 for block in _PARAGRAPH_SPLIT.split(text) if len(block.strip()) >= _MIN_PARAGRAPH_CHARS
    )


def _link_density(document: ExtractedDocument) -> float:
    body_length = len(document.body_text.strip())
    if body_length == 0:
        return 0.0
    return min(document.link_text_chars / body_length, 1.0)


def _metadata_present(document: ExtractedDocument) -> int:
    return sum(
        1
        for value in (
            document.title,
            document.canonical_url,
            document.published_at,
            document.source_id,
        )
        if value
    )


def evaluate(
    document: ExtractedDocument,
    *,
    is_release: bool = False,
    config: GateConfig | None = None,
) -> GateResult:
    """Judge whether `document` holds usable fulltext.

    `is_release` selects the lower threshold: GitHub release bodies and
    changelog sections are complete documents even when short, whereas a
    300-character "article" is almost certainly a summary.
    """
    config = config or GateConfig()
    body = document.body_text.strip()
    body_chars = len(body)
    paragraphs = _paragraph_count(body)
    density = _link_density(document)

    def result(decision: Decision, reason: str | None) -> GateResult:
        return GateResult(decision, reason, body_chars, paragraphs, density)

    if body_chars == 0:
        return result(Decision.METADATA_ONLY, "EMPTY_BODY")

    lowered = body.lower()
    for marker in config.reject_markers:
        if marker in lowered:
            return result(Decision.REJECTED, "BLOCKED_PAGE")

    minimum = config.min_body_chars_release if is_release else config.min_body_chars_article
    if body_chars < minimum:
        return result(Decision.METADATA_ONLY, "BODY_TOO_SHORT")

    # Release bodies are legitimately single-block markdown, so the paragraph
    # and link-density heuristics apply to extracted articles only.
    if not is_release:
        if paragraphs < config.min_paragraphs_article:
            return result(Decision.REJECTED, "TOO_FEW_PARAGRAPHS")
        if density > config.max_link_density:
            return result(Decision.REJECTED, "LINK_DENSITY")

    if _metadata_present(document) < config.required_metadata_count:
        return result(Decision.REJECTED, "INSUFFICIENT_METADATA")

    return result(Decision.ACCEPTED, None)

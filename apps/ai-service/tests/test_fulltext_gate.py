"""Fulltext gate tests (AHR-SOURCE-900 §4.1).

The gate is the component that decides whether a source genuinely delivered
article text, so these cases encode the failure modes it exists to catch —
including two regressions found against live sources during TASK-M1-001.
"""

from __future__ import annotations

import pytest

from ahr.ingestion.fulltext_gate import Decision, ExtractedDocument, evaluate

PARAGRAPH = (
    "This is a substantive paragraph of article prose with enough length "
    "to represent real editorial content rather than a teaser."
)


def document(body: str, **overrides: object) -> ExtractedDocument:
    fields: dict[str, object] = {
        "title": "A title",
        "canonical_url": "https://example.com/a",
        "source_id": "example-source",
    }
    fields.update(overrides)
    return ExtractedDocument(body_text=body, **fields)  # type: ignore[arg-type]


def test_real_article_is_accepted() -> None:
    result = evaluate(document("\n".join([PARAGRAPH] * 4)))
    assert result.decision is Decision.ACCEPTED
    assert result.reason_code is None


def test_trafilatura_single_newline_paragraphs_are_counted() -> None:
    """Regression: trafilatura separates paragraphs with single newlines.

    Counting only blank-line-separated blocks scored every extracted article as
    one paragraph, rejecting all of them.
    """
    result = evaluate(document("\n".join([PARAGRAPH] * 4)))
    assert result.paragraph_count == 4
    assert result.decision is Decision.ACCEPTED


def test_markdown_blank_line_paragraphs_are_counted() -> None:
    result = evaluate(document("\n\n".join([PARAGRAPH] * 3)))
    assert result.paragraph_count == 3
    assert result.decision is Decision.ACCEPTED


def test_soft_wrapped_short_lines_do_not_count_as_paragraphs() -> None:
    result = evaluate(document("\n".join(["short line"] * 60)))
    assert result.decision is Decision.REJECTED
    assert result.reason_code == "TOO_FEW_PARAGRAPHS"


def test_feed_summary_is_metadata_not_fulltext() -> None:
    """A teaser must never be recorded as a successful fulltext extraction."""
    result = evaluate(document("A short teaser summary of the article."))
    assert result.decision is Decision.METADATA_ONLY
    assert result.reason_code == "BODY_TOO_SHORT"


@pytest.mark.parametrize(
    "marker",
    ["sign in to continue", "access denied", "verify you are human", "enable javascript"],
)
def test_blocked_pages_are_rejected(marker: str) -> None:
    result = evaluate(document(f"{marker} " + PARAGRAPH * 6))
    assert result.decision is Decision.REJECTED
    assert result.reason_code == "BLOCKED_PAGE"


def test_link_farm_is_rejected() -> None:
    body = "\n".join([PARAGRAPH] * 4)
    result = evaluate(document(body, link_text_chars=len(body)))
    assert result.decision is Decision.REJECTED
    assert result.reason_code == "LINK_DENSITY"


def test_prose_with_a_few_links_is_accepted() -> None:
    """Regression: density was computed against the whole page, so ordinary
    articles measured above the threshold and were wrongly rejected."""
    body = "\n".join([PARAGRAPH] * 4)
    result = evaluate(document(body, link_text_chars=int(len(body) * 0.1)))
    assert result.decision is Decision.ACCEPTED
    assert result.link_density == pytest.approx(0.1, abs=0.01)


def test_missing_metadata_is_rejected() -> None:
    result = evaluate(ExtractedDocument(body_text="\n".join([PARAGRAPH] * 4)))
    assert result.decision is Decision.REJECTED
    assert result.reason_code == "INSUFFICIENT_METADATA"


def test_empty_body_is_metadata_only() -> None:
    result = evaluate(document(""))
    assert result.decision is Decision.METADATA_ONLY
    assert result.reason_code == "EMPTY_BODY"


def test_release_uses_lower_threshold() -> None:
    """Release notes are complete documents even when short."""
    # Above the 80-char release minimum but below the 300-char article minimum.
    body = "## Changes\n* Fix streaming timeout on long responses\n* Honour Retry-After on 429"
    assert evaluate(document(body), is_release=True).decision is Decision.ACCEPTED
    # The same text judged as an article is too short to be a real body.
    assert evaluate(document(body), is_release=False).decision is Decision.METADATA_ONLY


def test_release_below_minimum_is_metadata_only() -> None:
    assert evaluate(document("bump"), is_release=True).decision is Decision.METADATA_ONLY

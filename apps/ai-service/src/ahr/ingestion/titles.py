"""Title sanitising.

Five sources were producing unusable titles in three distinct ways, and 28 of
the 43 items they had ingested were affected:

    huggingface-blog          "…Mind Reader? dlouapre • 20 days ago • 37"
    huggingface-daily-papers  "https://huggingface.co/papers/2607.23782"
    cohere-blog, meta-ai-blog  the URL again
    baai-community            one- and two-character stubs

Each looks like a separate adapter bug, but they are one failure: when the
heading selector misses, the extractor falls back to whatever text or href the
anchor carried, and that fallback is never checked for being a title at all.

Fixing it per adapter would mean five selectors to keep working against five
sites' redesigns. Sanitising centrally means a new source gets the same
protection without anyone remembering to add it, and the body — which we already
have — supplies a real title when the candidate is junk.

Nothing here invents a title: every replacement comes from the document itself,
so AHR-INGEST-1000 §5's ban on fabricated metadata still holds.
"""

from __future__ import annotations

import re

# Trailing listing metadata: author handle, then a relative or absolute date,
# then an upvote count, separated by bullets. Anchored to the end so a bullet
# inside a real title ("GPT-4 • the sequel") is left alone.
# "about" appears in the relative dates these listings render ("about 3 hours
# ago"); omitting it left every item under a day old undecorated.
_RELATIVE_DATE = (
    r"(?:about\s+|almost\s+|over\s+)?\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago"
)

_LISTING_SUFFIX = re.compile(
    rf"""
    \s+\S+                                  # author handle
    \s*[•·]\s*
    (?:
        {_RELATIVE_DATE}
      | [A-Z][a-z]{{2}}\s+\d{{1,2}},\s+\d{{4}}   # Oct 29, 2024
    )
    (?:\s*[•·]\s*\d+)?                      # optional upvote count
    \s*$
    """,
    re.VERBOSE,
)

# A bare relative date with no author, e.g. "… Model 4 days ago".
_TRAILING_AGO = re.compile(rf"\s*[•·]?\s*{_RELATIVE_DATE}\s*$")

_URL_ONLY = re.compile(r"^\s*https?://\S+\s*$", re.IGNORECASE)

# Link text a listing page uses instead of a heading.
_BOILERPLATE = {
    "read more",
    "read the blog",
    "read blog",
    "learn more",
    "continue reading",
    "see more",
    "view more",
    "更多",
    "阅读全文",
    "查看详情",
}

MIN_TITLE_CHARS = 4


def strip_listing_metadata(title: str) -> str:
    """Remove trailing author / date / upvote decoration from a card title."""
    cleaned = _LISTING_SUFFIX.sub("", title)
    cleaned = _TRAILING_AGO.sub("", cleaned)
    return cleaned.strip(" \t ·•-—|")


def is_usable(title: str | None) -> bool:
    """Whether this can be shown to a reader as the article's title."""
    if not title:
        return False
    text = title.strip()
    if len(text) < MIN_TITLE_CHARS:
        return False
    if _URL_ONLY.match(text):
        return False
    return text.lower().strip(" .·•") not in _BOILERPLATE


# Markdown fences, tables, quotes and YAML front-matter keys. Hugging Face model
# cards open with a front-matter block, so without this the first "title" found
# would be "language: en license: mit".
_FRONT_MATTER_KEY = re.compile(r"^[a-z_][a-z0-9_-]*:\s")


def _is_structural(line: str) -> bool:
    """True for markup scaffolding that is never an article title."""
    return line.startswith(("---", "```", "|", ">", "!", "<")) or bool(
        _FRONT_MATTER_KEY.match(line)
    )


def title_from_body(body_text: str | None, *, max_chars: int = 200) -> str | None:
    """Derive a title from the document body.

    Prefers a markdown heading, then the first non-trivial line. Used only when
    the extracted title is unusable, so a good title is never overridden.
    """
    if not body_text:
        return None

    lines = body_text.splitlines()
    in_fence = False
    # YAML front matter only counts when the very first line opens it, so a "---"
    # rule partway down the document is not read as a block delimiter.
    in_front_matter = bool(lines) and lines[0].strip() == "---"

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()

        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_front_matter and index > 0 and line == "---":
            in_front_matter = False
            continue
        if in_fence or in_front_matter or not line:
            continue

        heading = re.match(r"^#{1,3}\s+(.*)$", line)
        candidate = heading.group(1).strip() if heading else line

        if _is_structural(candidate) or not is_usable(candidate):
            continue

        return candidate[:max_chars].strip()

    return None


def resolve_title(
    candidate: str | None, *, body_text: str | None = None, fallback: str | None = None
) -> str | None:
    """Best available title, or None when the document supplies none.

    Order: the cleaned candidate, then the body, then the caller's fallback
    (normally the canonical URL, which at least identifies the item).
    """
    if candidate:
        cleaned = strip_listing_metadata(candidate)
        if is_usable(cleaned):
            return cleaned

    from_body = title_from_body(body_text)
    if from_body:
        return from_body

    return fallback

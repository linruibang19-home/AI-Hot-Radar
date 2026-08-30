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

# A second failure shape, found on 2026-08-29: the heading, the section label,
# the date and the opening of the body arrive concatenated with no separator,
# because the extractor took a container's text rather than the heading's.
#
#   Anthropic  "Previewing the Model Hardware StandardAnnouncementsAug 27, 2026We're opening…"
#   xAI        "Grok 4.6Aug 12, 2026Introducing Grok 4.6Aug 12, 2026IntroducingGrok 4.6…"
#   Mistral    "ResearchMathΣtralJuly 16, 2024By Mistral AI team"
#   Groq       "PlatformWhat is a Language Processing Unit?March 7, 2025"
#
# 37 of 3052 stored titles, across four sources. `strip_listing_metadata`
# cannot reach these: it removes *trailing* bullet-separated decoration, and
# here the junk is in front of, or fused into, the title.
#
# Length is deliberately not the signal. arXiv and Hugging Face Daily Papers
# carry genuinely long titles — "Engineering Signals of Human-AI Collaboration
# in the Agentic Coding Era: A Longitudinal Analysis of 33,228 Pull Requests…"
# is correct at 190 characters — so a threshold would delete real titles while
# leaving "Grok 4.6Aug 12, 2026…" untouched.
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_ABSOLUTE_DATE = rf"{_MONTH}\s+\d{{1,2}},\s+\d{{4}}"

# The unambiguous signal is a date with no whitespace on one side of it. A real
# title mentioning a date writes " on Aug 27, 2026"; only a concatenation
# produces "StandardAnnouncementsAug 27, 2026" or "Aug 11, 2026Introducing".
_GLUED_DATE = re.compile(rf"[a-z0-9)]{_ABSOLUTE_DATE}|{_ABSOLUTE_DATE}[A-Za-z]")

# Section labels these newsrooms render beside the heading. Kept as an explicit
# list rather than matching any lowercase-to-uppercase seam, because CamelCase
# names (DeepSWE, LoLCATs, GroqCloud) are ordinary inside a real title.
_SECTION_LABELS = (
    "Announcements",
    "Research",
    "Product",
    "Company",
    "Engineering",
    "Policy",
    "Solutions",
    "Platform",
    "Model Library",
    "Newsroom",
    "Customers",
    "Alignment",
    "Societal Impacts",
)
_LEADING_DATE = re.compile(rf"^\s*{_ABSOLUTE_DATE}(?=[A-Za-z])")
_DATE_SEAM = re.compile(rf"[a-z0-9)\]™.!?](?={_ABSOLUTE_DATE})")
_LEADING_SECTION = re.compile(rf"^\s*(?:{'|'.join(_SECTION_LABELS)})(?=[A-Z])")
_TRAILING_SECTION = re.compile(rf"(?<=[a-z0-9])(?:{'|'.join(_SECTION_LABELS)})\s*$")
_BARE_SECTION = re.compile(rf"^(?:{'|'.join(_SECTION_LABELS)})$")

# Stripping a leading section label needs a length guard, or a short title such
# as "NewsGuard" would lose its first word. Every observed concatenation is far
# longer than this.
_MIN_CHARS_FOR_SECTION_STRIP = 40


def looks_concatenated(title: str) -> bool:
    """Whether the extractor ran the heading into its surroundings."""
    if _GLUED_DATE.search(title):
        return True
    return bool(_LEADING_SECTION.match(title) and len(title) > _MIN_CHARS_FOR_SECTION_STRIP)


def split_concatenated(title: str) -> str:
    """Peel the date and section label off a run-together title.

    Applied repeatedly because the pieces nest: "Aug 7, 2026ProductImproving
    Fable 5's biology safeguards" needs the date gone before the section label
    reaches the front, and "Grok 4.6Aug 12, 2026Introducing Grok 4.6Aug 12,
    2026…" needs the cut at the first seam before the rest can be judged.

    Note there is no length guard in here. The one protecting short titles like
    "NewsGuard" lives in `looks_concatenated`, which decides whether this runs at
    all. Repeating it here silently broke Mistral's shape: cutting
    "ResearchMathΣtralJuly 16, 2024By Mistral AI team" at its seam leaves
    "ResearchMathΣtral", already under the threshold, so the label survived.
    """
    previous = None
    while previous != title:
        previous = title
        title = _LEADING_DATE.sub("", title).strip()
        seam = _DATE_SEAM.search(title)
        if seam:
            title = title[: seam.end()].strip()
        title = _LEADING_SECTION.sub("", title).strip()
        title = _TRAILING_SECTION.sub("", title).strip()
    return title


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
        if looks_concatenated(cleaned):
            split = split_concatenated(cleaned)
            # A split that leaves nothing but a section label, or that still
            # holds a date seam, did not come apart cleanly. Falling through to
            # the body is right there and only there: for a title whose only
            # defect was a glued-on date, the body's first line is usually the
            # opening sentence — "Grok 4.6 is now available via…" — which is
            # worse than the repaired "Grok 4.6 on Microsoft Foundry".
            cleaned = (
                split
                if is_usable(split)
                and not _BARE_SECTION.match(split)
                and not _GLUED_DATE.search(split)
                else ""
            )
        if is_usable(cleaned):
            return cleaned

    from_body = title_from_body(body_text)
    if from_body:
        return from_body

    return fallback

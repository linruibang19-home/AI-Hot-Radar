"""Contextual enrichment of chunks before embedding (M4).

A chunk taken from a release note reads, in full:

    - Authenticate skill registry downloads

Nine tokens, no product, no version, no date. Its vector is close to every
other security bullet ever written and close to nothing a reader would actually
ask. 849 of 3847 chunks in this corpus look like that, because the dominant
source type is a GitHub changelog.

The fix is the one Anthropic published as Contextual Retrieval: prepend the
context a human would need to make sense of the fragment — what it belongs to,
who published it, when, and which section it sits in — and embed *that*.

Critically the prefix is applied to the **embedding input only**, never to the
stored `body_text`. `rag_citation` quotes chunk text as evidence, and
AHR-SPEC-000 §7 requires a citation to be verifiable against the original; text
we synthesised is not in the source document and must never be presented as
though it were.
"""

from __future__ import annotations

from datetime import datetime

# Keeps a pathological heading chain from crowding out the passage itself.
MAX_HEADING_SEGMENTS = 3
MAX_TITLE_CHARS = 160


def build_embedding_text(
    *,
    body_text: str,
    title: str | None = None,
    source_name: str | None = None,
    published_at: datetime | None = None,
    heading_path: list[str] | None = None,
) -> str:
    """Compose what actually gets embedded: context header, then the passage.

    The header is deliberately terse. Every token spent on it is a token not
    spent on the passage, and the goal is disambiguation — telling this bullet
    apart from the same bullet in another project's changelog — not description.
    """
    parts: list[str] = []

    if title:
        parts.append(title.strip()[:MAX_TITLE_CHARS])
    if source_name:
        parts.append(source_name.strip())
    if published_at is not None:
        parts.append(published_at.date().isoformat())

    if heading_path:
        # The deepest headings carry the most specific context; a long chain
        # from a documentation page would otherwise dominate the header.
        segments = [segment.strip() for segment in heading_path if segment and segment.strip()]
        if segments:
            parts.append(" › ".join(segments[-MAX_HEADING_SEGMENTS:]))

    body = body_text.strip()
    if not parts:
        return body

    return f"{' · '.join(parts)}\n\n{body}"

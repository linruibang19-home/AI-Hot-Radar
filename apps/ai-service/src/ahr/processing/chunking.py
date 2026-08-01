"""Structure-aware chunking.

AHR-DATA-300 §6 rejects fixed-width splitting: chunks target 250-500 tokens,
cap at 700 with 40-80 tokens of overlap, and must not cross heading, list or
code-block boundaries. Every chunk keeps its `heading_path` and character
offsets so a RAG citation can point back into the original document.

Token counts are estimated rather than tokenizer-exact. The estimate only has
to be stable and roughly right to keep chunks in range, and avoiding a
tokenizer dependency keeps ingestion independent of the embedding model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TARGET_TOKENS = 400
MIN_TOKENS = 120
MAX_TOKENS = 700
OVERLAP_TOKENS = 60

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*```")

# Latin text averages ~4 characters per token; CJK is closer to 1.5 characters
# per token, so a single ratio would badly misjudge Chinese sources.
_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) or 1


@dataclass
class Chunk:
    ordinal: int
    text: str
    heading_path: list[str] = field(default_factory=list)
    token_count: int = 0
    char_start: int = 0
    char_end: int = 0


@dataclass
class _Block:
    """A structural unit that must never be split across chunks."""

    text: str
    heading_path: list[str]
    char_start: int
    char_end: int
    is_code: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def _split_blocks(markdown: str) -> list[_Block]:
    """Split text into paragraph/list/code blocks, tracking heading context."""
    blocks: list[_Block] = []
    heading_path: list[str] = []
    buffer: list[str] = []
    buffer_start = 0
    offset = 0
    in_code = False
    code_started_at = 0

    def flush(end: int, *, is_code: bool = False) -> None:
        nonlocal buffer, buffer_start
        text = "\n".join(buffer).strip()
        if text:
            blocks.append(
                _Block(
                    text=text,
                    heading_path=list(heading_path),
                    char_start=buffer_start,
                    char_end=end,
                    is_code=is_code,
                )
            )
        buffer = []

    for line in markdown.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        line_start = offset
        offset += len(line)

        if _FENCE_RE.match(stripped):
            if in_code:
                buffer.append(stripped)
                flush(offset, is_code=True)
                in_code = False
            else:
                flush(line_start)
                in_code = True
                code_started_at = line_start
                buffer_start = code_started_at
                buffer.append(stripped)
            continue

        if in_code:
            buffer.append(stripped)
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush(line_start)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            # Replace same-or-deeper levels so the path reflects real nesting.
            heading_path = heading_path[: level - 1] + [title]
            buffer_start = offset
            continue

        if not stripped.strip():
            flush(line_start)
            buffer_start = offset
            continue

        if not buffer:
            buffer_start = line_start
        buffer.append(stripped)

    flush(offset, is_code=in_code)
    return blocks


def _overlap_tail(text: str) -> str:
    """Trailing sentences worth roughly OVERLAP_TOKENS, for context carry-over."""
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    tail: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        tokens = estimate_tokens(sentence)
        if total + tokens > OVERLAP_TOKENS and tail:
            break
        tail.insert(0, sentence)
        total += tokens
    return " ".join(tail).strip()


def chunk_document(markdown: str) -> list[Chunk]:
    """Split a document into retrievable chunks."""
    if not markdown or not markdown.strip():
        return []

    blocks = _split_blocks(markdown)
    if not blocks:
        return []

    chunks: list[Chunk] = []
    current: list[_Block] = []
    current_tokens = 0
    carry = ""

    def emit() -> None:
        nonlocal current, current_tokens, carry
        if not current:
            return
        body = "\n\n".join(block.text for block in current)
        text = f"{carry}\n\n{body}".strip() if carry else body
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                text=text,
                heading_path=current[0].heading_path,
                token_count=estimate_tokens(text),
                char_start=current[0].char_start,
                char_end=current[-1].char_end,
            )
        )
        carry = _overlap_tail(body) if not current[-1].is_code else ""
        current = []
        current_tokens = 0

    for block in blocks:
        # A single oversized block (long code listing, dense table) is kept whole
        # rather than cut mid-structure; §6 forbids crossing those boundaries.
        if block.tokens > MAX_TOKENS:
            emit()
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    text=block.text,
                    heading_path=block.heading_path,
                    token_count=block.tokens,
                    char_start=block.char_start,
                    char_end=block.char_end,
                )
            )
            carry = ""
            continue

        # Start a new chunk when the heading context changes, so a chunk never
        # mixes two sections. The overlap tail is dropped as well: carrying the
        # previous section's sentences into this one would reintroduce exactly
        # the mixing this branch exists to prevent.
        if current and block.heading_path != current[0].heading_path:
            emit()
            carry = ""

        if current_tokens + block.tokens > MAX_TOKENS:
            emit()

        current.append(block)
        current_tokens += block.tokens

        if current_tokens >= TARGET_TOKENS:
            emit()

    emit()

    # Fold a short trailing chunk into its predecessor rather than indexing a
    # fragment that carries no standalone meaning — but only within the same
    # section, since merging across a heading would defeat the whole point of
    # structure-aware chunking.
    if (
        len(chunks) > 1
        and chunks[-1].token_count < MIN_TOKENS
        and chunks[-1].heading_path == chunks[-2].heading_path
    ):
        tail = chunks.pop()
        previous = chunks[-1]
        merged = f"{previous.text}\n\n{tail.text}"
        chunks[-1] = Chunk(
            ordinal=previous.ordinal,
            text=merged,
            heading_path=previous.heading_path,
            token_count=estimate_tokens(merged),
            char_start=previous.char_start,
            char_end=tail.char_end,
        )

    return chunks

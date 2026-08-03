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

# A block that exceeds MAX_TOKENS used to be emitted whole, on the reasoning
# that §6 forbids splitting a code listing or table. That is right about
# structure and wrong about retrieval: the largest chunk in the corpus reached
# 24 979 tokens, and the embedding provider only sees the first few thousand
# characters, so 94% of it was invisible to search. A block above this cap is
# now split at the safest boundary available — a chunk that cannot be embedded
# in full is not a chunk, it is a hole in the index.
HARD_MAX_TOKENS = 1200

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
    # (level, title) pairs, not bare titles. Truncating by list position assumed
    # index 0 was a level-1 heading, but most bodies here start at "##" because
    # the "#" is the document title — so every sibling section was recorded as a
    # child of the previous one and heading paths grew monotonically down the
    # document. A release note ended up with paths like
    # "Highlights › Changelog › @mastra/next@0.2.4 › Patch Changes", which is
    # not the document's structure and made sibling sections look unrelated.
    heading_stack: list[tuple[int, str]] = []
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
                    heading_path=[title for _, title in heading_stack],
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
            # Drop every heading at this level or deeper, then push. Comparing
            # levels rather than counting positions is what makes a sibling a
            # sibling regardless of which level the document happens to start at.
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
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
        # Beyond HARD_MAX_TOKENS that preference loses to being searchable at
        # all, so the block is split on line boundaries.
        if block.tokens > MAX_TOKENS:
            emit()
            for piece in _split_oversized(block):
                chunks.append(
                    Chunk(
                        ordinal=len(chunks),
                        text=piece.text,
                        heading_path=piece.heading_path,
                        token_count=piece.tokens,
                        char_start=piece.char_start,
                        char_end=piece.char_end,
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
    return _merge_short(chunks)


def _split_oversized(block: _Block) -> list[_Block]:
    """Break a block too large to embed into line-aligned pieces.

    Lines rather than sentences: an oversized block here is almost always a
    changelog, a table or a code listing, where the line is the meaningful unit
    and sentence splitting would cut mid-row.
    """
    if block.tokens <= HARD_MAX_TOKENS:
        return [block]

    pieces: list[_Block] = []
    buffer: list[str] = []
    # Character counts rather than a running sum of per-line token estimates.
    # estimate_tokens truncates to an int and ignores the newlines that joining
    # adds back, so summing per line undercounts — the first version of this
    # produced 1439-token pieces against a 1200 cap.
    buffer_cjk = 0
    buffer_other = 0
    offset = block.char_start

    def measure(text: str) -> tuple[int, int]:
        cjk = len(_CJK_RE.findall(text))
        return cjk, len(text) - cjk

    def flush() -> None:
        nonlocal buffer, buffer_cjk, buffer_other, offset
        if not buffer:
            return
        text = "\n".join(buffer)
        pieces.append(
            _Block(
                text=text,
                heading_path=block.heading_path,
                char_start=offset,
                char_end=offset + len(text),
                is_code=block.is_code,
            )
        )
        offset += len(text) + 1
        buffer = []
        buffer_cjk = 0
        buffer_other = 0

    for line in block.text.splitlines():
        cjk, other = measure(line)
        # +1 for the newline this line contributes once joined.
        projected = int((buffer_cjk + cjk) / 1.5 + (buffer_other + other + 1) / 4)
        if buffer and projected > HARD_MAX_TOKENS:
            flush()
            cjk, other = measure(line)
        buffer.append(line)
        buffer_cjk += cjk
        buffer_other += other + 1

    flush()
    return pieces or [block]


def _common_prefix(left: list[str], right: list[str]) -> list[str]:
    shared: list[str] = []
    for a, b in zip(left, right, strict=False):
        if a != b:
            break
        shared.append(a)
    return shared


def _mergeable_headings(left: list[str], right: list[str]) -> bool:
    """Whether two sections are close enough to share a chunk.

    Identical paths obviously qualify. Siblings under a common parent do too:
    release notes give every version and every category its own heading
    ("Changelog › Patch Changes", "Changelog › Minor Changes"), so requiring an
    exact match left 861 fragments unmerged — the rule blocked precisely the
    documents that needed it most.

    Top-level sections still never merge. Combining "Installation" with
    "Breaking Changes" would produce a chunk that answers neither question,
    which is the failure §6's boundary rule exists to prevent.
    """
    if left == right:
        return True

    # Siblings only: same depth, same parent. An earlier version asked merely
    # for a shared prefix, which also matched a parent against its own child and
    # collapsed "Guide" into "Guide › Retrieval" — losing the child's path, and
    # with it the ability to say which section a citation came from.
    return len(left) == len(right) and len(left) > 1 and left[:-1] == right[:-1]


def _merge_short(chunks: list[Chunk]) -> list[Chunk]:
    """Fold undersized chunks into a neighbour in the same section.

    Only the final chunk used to be folded, which is enough for prose but not
    for the release notes that dominate this corpus: a changelog of twenty
    one-line bullets produced twenty chunks under 50 tokens and merged only the
    last. 849 of 3847 stored chunks ended up below 50 tokens — fragments like
    "- Authenticate skill registry downloads" that carry no standalone meaning,
    match on trivial overlap, and push substantive passages out of the top-k.

    Merging stays inside a heading path: joining across sections would undo the
    structure-aware split this module exists to perform.
    """
    if len(chunks) < 2:
        return chunks

    merged: list[Chunk] = []
    for chunk in chunks:
        if (
            merged
            and chunk.token_count < MIN_TOKENS
            and _mergeable_headings(merged[-1].heading_path, chunk.heading_path)
            and merged[-1].token_count + chunk.token_count <= MAX_TOKENS
        ):
            previous = merged[-1]
            text = f"{previous.text}\n\n{chunk.text}"
            merged[-1] = Chunk(
                ordinal=previous.ordinal,
                text=text,
                # The shared ancestry, so the path still describes everything the
                # chunk now contains rather than only its first section.
                heading_path=_common_prefix(previous.heading_path, chunk.heading_path),
                token_count=estimate_tokens(text),
                char_start=previous.char_start,
                char_end=chunk.char_end,
            )
            continue

        merged.append(
            Chunk(
                ordinal=len(merged),
                text=chunk.text,
                heading_path=chunk.heading_path,
                token_count=chunk.token_count,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
            )
        )

    return merged

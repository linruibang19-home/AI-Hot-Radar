"""Near-duplicate detection.

AHR-DATA-300 §5 defines three distinct layers that must not be conflated:

1. exact duplicate  - same external id, canonical URL or content hash
2. near duplicate   - syndicated or lightly rewritten copy (this module)
3. same event       - different reports of one happening, which is Story
                      clustering in M3 and deliberately NOT handled here

SimHash is used because it detects "mostly the same words" cheaply and
symmetrically, which is what syndication looks like.
"""

from __future__ import annotations

import hashlib
import re

HASH_BITS = 64

# Near-duplicate threshold in Hamming distance. 3 is the conventional operating
# point for 64-bit SimHash: it catches boilerplate-differing reposts without
# merging two genuinely different articles on the same topic.
NEAR_DUPLICATE_DISTANCE = 3

_TOKEN_RE = re.compile(r"[\w一-鿿]+")


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = _TOKEN_RE.findall(lowered)
    # Character bigrams for CJK, where whitespace does not delimit words.
    bigrams = [lowered[i : i + 2] for i in range(len(lowered) - 1) if "一" <= lowered[i] <= "鿿"]
    return words + bigrams


def simhash(text: str) -> int:
    """64-bit SimHash of `text`. Returns 0 for empty input."""
    tokens = _tokens(text)
    if not tokens:
        return 0

    vector = [0] * HASH_BITS
    for token in tokens:
        digest = int(hashlib.blake2b(token.encode("utf-8"), digest_size=8).hexdigest(), 16)
        for bit in range(HASH_BITS):
            vector[bit] += 1 if digest >> bit & 1 else -1

    value = 0
    for bit in range(HASH_BITS):
        if vector[bit] > 0:
            value |= 1 << bit
    return value


def hamming_distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def is_near_duplicate(left: int, right: int, *, threshold: int = NEAR_DUPLICATE_DISTANCE) -> bool:
    """True when two SimHashes are close enough to be the same article.

    Two zero hashes mean both texts were empty, which is not evidence of
    duplication.
    """
    if not left or not right:
        return False
    return hamming_distance(left, right) <= threshold


def to_signed_64(value: int) -> int:
    """Map an unsigned 64-bit hash into PostgreSQL BIGINT range."""
    return value - (1 << 64) if value >= (1 << 63) else value


def from_signed_64(value: int) -> int:
    return value + (1 << 64) if value < 0 else value

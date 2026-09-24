"""The sentences an answer publishes, each with the citation markers it carries.

Support used to be judged once per citation, against one sentence — its
`claim_text` — while a marker is routinely shared: on the frozen golden run 155
of 272 citations back two or more sentences. The unit a reader checks is the
pair they see: one sentence, one `[n]` in it. Anchor selection (ADR-0037) and
the generation evaluation both work on those pairs, and both take them from
here.

Deleting weak pairs was measured and rejected (ADR-0037): of 23 sentences a
strict per-pair gate would remove, at least 14 are in the source. The
cross-encoder ranks relevance; it is not an entailment judge.

Sentences are enumerated exactly as `answer.drop_uncited_sentences` splits
them, so a sentence here is a sentence that function would keep or drop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Kept identical to `answer._BOUND_SENTENCE_RE` / `_BOUND_CITATION_RE`.
_SENTENCE_RE = re.compile(r"[^。！？\n]+(?:[。！？](?:\s*\[\d+\])*)?")
_MARKER_RE = re.compile(r"\s*\[(\d+)\]")


@dataclass(frozen=True)
class CitedSentence:
    key: tuple[int, int]  # (line index, sentence index within the line)
    text: str  # the sentence as scored: markers removed
    numbers: tuple[int, ...]  # distinct markers, in reading order


def cited_sentences(answer_markdown: str) -> list[CitedSentence]:
    """Every sentence carrying at least one bound `[n]`, keyed by position."""
    found: list[CitedSentence] = []
    for line_index, line in enumerate(answer_markdown.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        content = stripped[2:].strip() if stripped.startswith("- ") else stripped
        matches = [m for m in _SENTENCE_RE.finditer(content) if m.group(0).strip()]
        for sentence_index, match in enumerate(matches):
            numbers = tuple(dict.fromkeys(int(n) for n in _MARKER_RE.findall(match.group(0))))
            if numbers:
                text = _MARKER_RE.sub("", match.group(0)).strip()
                found.append(CitedSentence((line_index, sentence_index), text, numbers))
    return found

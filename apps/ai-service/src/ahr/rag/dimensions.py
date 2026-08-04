"""`directness` and `source_fit` — the last two reranker dimensions of §6.

`AHR-RAG-400` §6 specifies four outputs from the rerank stage: `relevance`,
`temporal_fit`, `directness` and `source_fit`. The cross-encoder supplies
`relevance` (B4) and `temporal.py` supplies `temporal_fit` (B7). These are the
remaining two, and like `temporal_fit` they are applied *after* the
cross-encoder rather than folded into fusion — B8 showed the reranker rewrites
whatever order fusion produces, so a signal that must survive has to be applied
downstream of it.

Both are derived from metadata already in hand. Neither costs a model call:
a per-passage LLM judgement would multiply the query's 10.5s p50 by the number
of candidates, which is not a trade the spec asks for.

**directness — is the document *about* this, or does it merely mention it?**

The failure this addresses is the one B1 found and B2 fixed only partly. Asking
which model uses MXFP4 quantisation returned, above the answer:

    vLLM v0.26.0 release notes     <- mentions MXFP4 in one bullet
    Kimi K3: 2.8T parameters and MXFP4 quantisation   <- is about it

Both passages contain the token. The difference is that one document's *title*
carries the subject and the other's does not. A release note that lists a
supported format in passing is a weaker answer to "which model uses it" than a
document whose subject is that model, and title overlap is a cheap, honest
proxy for that distinction.

**source_fit — does this kind of source answer this kind of question?**

This corpus is 53 GitHub Release feeds, plus media and expert newsletters. A
release note is the ideal evidence for "what changed last week" and poor
evidence for "explain what MoE routing is" — it states, it does not explain.
Ranking by relevance alone cannot see that, because both are genuinely about
the subject.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# §6 bounds every metadata adjustment. These sit at or below the boosts already
# in fusion.py (+0.08 primary, -0.15 opinion-for-fact) for the same reason
# recorded there: the first B3 run applied ±0.05-0.15 to scores whose entire
# spread was 0.008, and metadata silently became the ranking function.
DIRECTNESS_WEIGHT = 0.10
SOURCE_FIT_WEIGHT = 0.08

# How well each source tier answers each kind of question, in [-1, 1].
#
# `explainer` is the only row with a negative entry, and it is the point of the
# table: a changelog is a primary source and still a bad answer to "how does
# this work". Everything else prefers primary or is indifferent, which matches
# how the corpus is actually built.
SOURCE_AFFINITY: dict[str, dict[str, float]] = {
    "recent_updates": {"primary": 1.0, "secondary": 0.3, "expert": 0.2, "community": 0.0},
    "fact_check": {"primary": 1.0, "secondary": 0.4, "expert": 0.4, "community": -0.2},
    "timeline": {"primary": 1.0, "secondary": 0.4, "expert": 0.2, "community": 0.0},
    "explainer": {"primary": -0.3, "secondary": 0.5, "expert": 1.0, "community": 0.2},
    "comparison": {"primary": 0.5, "secondary": 0.6, "expert": 0.8, "community": 0.0},
}

# Tokens: CJK runs character-by-character, Latin word-by-word. The same split
# the sparse channel relies on, for the same reason — one rule, both languages.
_CJK = re.compile(r"[一-鿿぀-ヿ]")
_TOKEN = re.compile(r"[一-鿿぀-ヿ]|[a-z0-9][a-z0-9.+-]*")

# A one-letter Latin token is punctuation or an article and matching on it would
# make every title look direct. The floor applies to Latin only: a CJK character
# *is* a term, and a blanket `len >= 2` deletes every one of them — which would
# have scored `directness` at exactly 0.0 for every Chinese question, silently.
# B2 hit the same shape of bug when the sparse channel returned nothing for 15
# pure-Chinese questions.
MIN_LATIN_TERM_CHARS = 2


@dataclass
class Candidate:
    key: str
    relevance: float
    title: str
    source_tier: str | None = None


def tokenize(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(text.lower())
        if _CJK.match(token) or len(token) >= MIN_LATIN_TERM_CHARS
    }


def directness(question: str, title: str) -> float:
    """Share of the question's terms that appear in the document title, in [0, 1].

    Deliberately not the passage body: the body is what the cross-encoder
    already scored, so measuring it again would double-count relevance rather
    than add a dimension. The title is the one piece of evidence about what the
    document is *for*.
    """
    terms = tokenize(question)
    if not terms:
        return 0.0
    return len(terms & tokenize(title)) / len(terms)


def source_fit(query_type: str, source_tier: str | None) -> float:
    """Affinity of this source tier for this kind of question, in [-1, 1].

    Unknown tiers and unknown query types score 0 — neutral, not penalised. A
    missing tier is missing information, and treating it as a bad source would
    silently demote everything the enrichment step has not reached yet.
    """
    if not source_tier:
        return 0.0
    return SOURCE_AFFINITY.get(query_type, {}).get(source_tier, 0.0)


def _normalise(values: list[float]) -> list[float]:
    """Map onto [0, 1]. A flat list becomes all-1.0, never all-0.

    Same choice as `temporal._normalise`: collapsing ties to zero would hand
    the whole decision to the adjustment, which is the opposite of a bounded
    one.
    """
    if not values:
        return []
    low, high = min(values), max(values)
    spread = high - low
    if spread <= 0:
        return [1.0] * len(values)
    return [(value - low) / spread for value in values]


def apply_dimensions(
    candidates: list[Candidate],
    *,
    question: str,
    query_type: str,
    directness_weight: float = DIRECTNESS_WEIGHT,
    source_fit_weight: float = SOURCE_FIT_WEIGHT,
) -> list[str]:
    """Reorder by relevance adjusted with the two remaining §6 dimensions.

    Returns keys in the new order. Relevance keeps the dominant share: these
    dimensions break ties and correct the "mentions it in passing" case, and are
    not meant to overturn a passage that plainly answers the question.
    """
    if not candidates:
        return []

    relevance = _normalise([c.relevance for c in candidates])
    adjusted: list[tuple[float, str]] = []
    for base, candidate in zip(relevance, candidates, strict=True):
        score = (
            base
            + directness_weight * directness(question, candidate.title)
            + source_fit_weight * source_fit(query_type, candidate.source_tier)
        )
        # Ties broken by key so a rerun is reproducible.
        adjusted.append((score, candidate.key))

    adjusted.sort(key=lambda pair: (-pair[0], pair[1]))
    return [key for _, key in adjusted]

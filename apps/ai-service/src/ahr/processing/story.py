"""Event clustering into Stories (M3, AHR-DATA-300 §8).

A Story is one real-world event. Several outlets reporting the same release is
the signal the hot list actually wants; until this exists, "independent source
count" is approximated by near-duplicate grouping and is nearly always 1.

The spec's feature set is:

    0.35 title_and_summary_embedding
    0.25 entity_overlap
    0.15 action_object_match
    0.10 url_or_quote_link
    0.10 time_proximity
    0.05 topic_overlap

Two of those are not available yet and are handled explicitly rather than
silently scored as zero:

* embeddings arrive in M4, so the 0.35 slot is filled by a lexical title
  similarity. It is a weaker proxy — it cannot see that "开源" and "开放权重"
  mean the same thing — so the threshold is set higher than an embedding-based
  system would need, trading recall for purity. AHR-KPI-003 measures purity.
* url_or_quote_link needs outbound links, which ingestion does not extract.
  Its weight is redistributed rather than counted as a zero, because a constant
  zero term would drag every pair's score down uniformly and make the threshold
  meaningless.

Hard rules veto a merge regardless of score. The one that matters most in
practice is the version rule: "DeepSeek V3" and "DeepSeek V4-Flash" share a
company, a product family and most of their vocabulary, and merging them would
be a factual error, not a ranking nuisance.
"""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CLUSTER_ALGORITHM_VERSION = "story-v1"

# docs/spec/03 §8: candidate window is 72 hours either side of publication.
CANDIDATE_WINDOW_HOURS = 72.0

# Weights for the features that are actually computable today. They are
# renormalised to sum to 1 so the score stays on [0, 1] and the threshold means
# the same thing before and after M4 restores the embedding term.
FEATURE_WEIGHTS = {
    "title_similarity": 0.35,
    "entity_overlap": 0.25,
    "action_object_match": 0.15,
    "time_proximity": 0.10,
    "topic_overlap": 0.05,
}
_WEIGHT_SUM = sum(FEATURE_WEIGHTS.values())

# Above this, merge automatically. Deliberately high: AHR-KPI-003 is a purity
# target, and a lexical stand-in for embeddings makes false merges more likely
# than false splits.
MERGE_THRESHOLD = 0.52

# Between this and MERGE_THRESHOLD the pair is recorded in cluster_suggestion
# for review instead of being merged.
SUGGEST_THRESHOLD = 0.42

# Ranking for primary-source selection, from docs/spec/03 §8:
# 官方当事方 > 官方文档/仓库 > 论文 > 权威媒体 > 技术作者 > 聚合转载
SOURCE_TIER_RANK = {"primary": 0, "secondary": 2, "expert": 3}
UNKNOWN_TIER_RANK = 4

# Content types that identify an item as the originating announcement rather
# than coverage of one.
ANNOUNCEMENT_TYPES = {"model_release", "product_release", "api_update"}

# Tokens that carry no topical signal; without this every release title matches
# every other one on "发布" and "release".
STOPWORDS = {
    "发布",
    "更新",
    "推出",
    "上线",
    "正式",
    "版本",
    "模型",
    "release",
    "releases",
    "update",
    "updates",
    "new",
    "the",
    "and",
    "for",
    "with",
    "版",
    "ai",
}

_VERSION_RE = re.compile(
    r"""
    (?<![a-z0-9])            # not mid-token
    (?:
        v\.?\d+(?:\.\d+)*    # v1, v0.26.0, V4
      | b\d{3,}              # llama.cpp build numbers: b10217
      | \d+\.\d+(?:\.\d+)*   # 1.5, 4.6, 0.26.0
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class Candidate:
    """One item as the clusterer sees it."""

    item_id: uuid.UUID
    title: str
    source_id: str
    organization: str | None
    source_tier: str
    content_type: str | None
    published_at: datetime | None
    quality_score: float | None
    entity_ids: frozenset[str] = frozenset()
    topic_ids: frozenset[str] = frozenset()
    tokens: frozenset[str] = field(default_factory=frozenset)
    versions: frozenset[str] = field(default_factory=frozenset)


def normalize_title(title: str) -> str:
    """Fold width and case so "ＧＰＴ" and "gpt" compare equal."""
    return unicodedata.normalize("NFKC", title or "").lower().strip()


def extract_versions(title: str) -> frozenset[str]:
    """Version-like tokens, normalised so "V4" and "v4" collide."""
    found = {
        match.group(0).lower().lstrip("v").lstrip(".") for match in _VERSION_RE.finditer(title)
    }
    return frozenset(token for token in found if token)


def tokenize(title: str) -> frozenset[str]:
    """Latin words plus CJK bigrams.

    Chinese has no spaces, so single characters are far too common to
    discriminate and whole strings never match. Bigrams are the standard
    compromise and need no segmentation dictionary.
    """
    normalized = normalize_title(title)
    tokens: set[str] = set()

    for word in re.findall(r"[a-z0-9][a-z0-9.\-_]*", normalized):
        if word not in STOPWORDS and len(word) > 1:
            tokens.add(word)
        # Also emit the parts of a compound. Product names are written
        # inconsistently across outlets — "DeepSeek-V4-Flash", "DeepSeek
        # V4-Flash" and "DeepSeek V4-Flash-0731" are the same release — and
        # without this the whole-token forms never match each other.
        parts = [part for part in re.split(r"[.\-_]+", word) if len(part) > 1]
        if len(parts) > 1:
            for part in parts:
                # Bare numbers ("0731", "26") are noise; the version rule reads
                # them separately and far more carefully.
                if part.isdigit() or part in STOPWORDS:
                    continue
                tokens.add(part)

    cjk = re.findall(r"[一-鿿]+", normalized)
    for run in cjk:
        if len(run) == 1:
            tokens.add(run)
            continue
        for index in range(len(run) - 1):
            bigram = run[index : index + 2]
            if bigram not in STOPWORDS:
                tokens.add(bigram)

    return frozenset(tokens)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


# Below this, a set is too small for the overlap coefficient to mean anything:
# one shared element out of one scores a perfect 1.0.
_MIN_SET_FOR_OVERLAP = 3


def containment(left: frozenset[str], right: frozenset[str]) -> float:
    """Overlap coefficient: shared / size of the smaller set.

    Jaccard is wrong here and measurably so. A changelog entry carrying 5
    entities and a news write-up carrying 10 that agree on the 2 entities the
    event is actually about score Jaccard 0.15 — indistinguishable from
    unrelated — because the union is dominated by incidental mentions each side
    happens to name. Containment reads the same pair as 0.40.

    Falls back to Jaccard for very small sets, where containment saturates: a
    single shared entity out of one would otherwise be a perfect match.
    """
    if not left or not right:
        return 0.0
    smaller = min(len(left), len(right))
    if smaller < _MIN_SET_FOR_OVERLAP:
        return jaccard(left, right)
    return len(left & right) / smaller


def time_proximity(left: datetime | None, right: datetime | None) -> float:
    """1.0 for simultaneous, decaying to 0 at the edge of the window.

    Missing timestamps score neutral rather than zero: several changelog sources
    publish without a date, and penalising them would make their events
    un-clusterable.
    """
    if left is None or right is None:
        return 0.5
    hours = abs((left - right).total_seconds()) / 3600.0
    if hours >= CANDIDATE_WINDOW_HOURS:
        return 0.0
    return 1.0 - (hours / CANDIDATE_WINDOW_HOURS)


def action_object_match(left: Candidate, right: Candidate) -> float:
    """Do the two items appear to be about the same subject and act?

    Approximated by shared model/product entities plus compatible content
    types. A llama.cpp release that merely mentions DeepSeek shares the DeepSeek
    entity but not the subject, which is why entity overlap alone is not enough.
    """
    shared = left.entity_ids & right.entity_ids
    if not shared:
        return 0.0

    # Both announcements, or both coverage: same kind of act.
    left_announce = (left.content_type or "") in ANNOUNCEMENT_TYPES
    right_announce = (right.content_type or "") in ANNOUNCEMENT_TYPES
    same_kind = left_announce == right_announce

    # The share has to be substantial relative to the smaller item, otherwise a
    # single incidental mention counts as a subject match.
    smaller = min(len(left.entity_ids), len(right.entity_ids)) or 1
    coverage = len(shared) / smaller

    return coverage * (1.0 if same_kind else 0.6)


@dataclass
class PairScore:
    total: float
    features: dict[str, float]
    veto: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"total": round(self.total, 5), "features": self.features, "veto": self.veto}


def version_conflict(left: Candidate, right: Candidate) -> bool:
    """True when the two titles name different versions.

    docs/spec/03 §8: "不同模型版本不得仅因公司相同合并". If both titles carry
    version tokens and they are disjoint, these are different releases however
    similar the wording.
    """
    if not left.versions or not right.versions:
        return False
    return not (left.versions & right.versions)


def score_pair(left: Candidate, right: Candidate) -> PairScore:
    features = {
        "title_similarity": containment(left.tokens, right.tokens),
        "entity_overlap": containment(left.entity_ids, right.entity_ids),
        "action_object_match": action_object_match(left, right),
        "time_proximity": time_proximity(left.published_at, right.published_at),
        "topic_overlap": containment(left.topic_ids, right.topic_ids),
    }

    # Topics are absent on 39% of enriched items, so a zero there usually means
    # "not labelled", not "different subject". Scoring absence as dissimilarity
    # penalises exactly the items the pipeline knows least about, so the term is
    # dropped for the pair and the remaining weights are renormalised.
    applicable = dict(FEATURE_WEIGHTS)
    if not left.topic_ids or not right.topic_ids:
        applicable.pop("topic_overlap")

    weight_sum = sum(applicable.values())
    total = sum(weight * features[name] for name, weight in applicable.items()) / weight_sum
    rounded = {name: round(value, 4) for name, value in features.items()}

    if version_conflict(left, right):
        return PairScore(total=total, features=rounded, veto="version_conflict")

    # Never merge two items from one source, whatever their type.
    #
    # A Story exists to count independent corroboration, and two items from the
    # same publisher contribute nothing to that count — so merging them cannot
    # improve the ranking, but it can and did produce wrong groupings. On the
    # real corpus the highest-scoring pairs included four separate OpenAI status
    # incidents merging into one "outage", and six Together AI posts whose
    # titles all extracted as "Read More" merging into one event. Both are the
    # same failure: high lexical similarity within one publisher's house style.
    if left.source_id == right.source_id:
        return PairScore(total=total, features=rounded, veto="same_source")

    return PairScore(total=total, features=rounded)


def primary_rank(candidate: Candidate) -> tuple[int, int, float]:
    """Sort key for primary-source selection; lower is better.

    An official announcement outranks commentary even from the same tier, which
    is what "官方当事方 > … > 聚合转载" means in practice.
    """
    tier = SOURCE_TIER_RANK.get(candidate.source_tier, UNKNOWN_TIER_RANK)
    announcement = 0 if (candidate.content_type or "") in ANNOUNCEMENT_TYPES else 1
    return (tier, announcement, -(candidate.quality_score or 0.0))


def independent_sources(members: list[Candidate]) -> int:
    """Distinct publishers, counted by organisation.

    Two feeds from one company are not independent corroboration, so the count
    is over organisation rather than source id; sources without an organisation
    fall back to their own id.
    """
    keys = {member.organization or member.source_id for member in members}
    return len(keys)


class Cluster:
    """A growing group of items believed to describe one event."""

    def __init__(self, seed: Candidate) -> None:
        self.members: list[Candidate] = [seed]
        self.scores: dict[uuid.UUID, PairScore] = {}

    def accepts(self, candidate: Candidate) -> tuple[bool, PairScore | None, str | None]:
        """Score against every member; a veto anywhere blocks the merge.

        Complete-linkage rather than single-linkage: with single linkage a chain
        of individually-plausible pairs merges two clearly different events.
        """
        best: PairScore | None = None
        for member in self.members:
            score = score_pair(member, candidate)
            if score.veto:
                return False, score, score.veto
            if best is None or score.total < best.total:
                best = score  # weakest link decides
        if best is None:
            return False, None, None
        return best.total >= MERGE_THRESHOLD, best, None

    def add(self, candidate: Candidate, score: PairScore) -> None:
        self.members.append(candidate)
        self.scores[candidate.item_id] = score

    def primary(self) -> Candidate:
        return min(self.members, key=primary_rank)

    def occurred_at(self) -> datetime | None:
        stamps = [m.published_at for m in self.members if m.published_at]
        return min(stamps) if stamps else None


def cluster(
    candidates: list[Candidate],
) -> tuple[list[Cluster], list[tuple[Candidate, Candidate, PairScore]]]:
    """Greedy agglomeration over the candidate window.

    Items are processed newest first so an official announcement, which usually
    lands first, tends to seed the cluster rather than join one.
    """
    ordered = sorted(
        candidates,
        key=lambda c: c.published_at or datetime.min.replace(tzinfo=None),
        reverse=True,
    )

    clusters: list[Cluster] = []
    suggestions: list[tuple[Candidate, Candidate, PairScore]] = []

    for candidate in ordered:
        placed = False
        for existing in clusters:
            within_window = any(
                time_proximity(member.published_at, candidate.published_at) > 0
                for member in existing.members
            )
            if not within_window:
                continue

            accepted, score, veto = existing.accepts(candidate)
            if accepted and score is not None:
                existing.add(candidate, score)
                placed = True
                break
            if (
                score is not None
                and veto is None
                and SUGGEST_THRESHOLD <= score.total < MERGE_THRESHOLD
            ):
                suggestions.append((existing.members[0], candidate, score))

        if not placed:
            clusters.append(Cluster(candidate))

    return clusters, suggestions


def slugify(title: str, occurred: datetime | None) -> str:
    """Stable, readable slug. Latin-only titles keep their words."""
    normalized = normalize_title(title)
    latin = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    stem = latin[:60] if len(latin) >= 8 else ""
    date_part = (occurred or datetime.now()).strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:6]
    return (
        f"{date_part}-{stem}-{suffix}".replace("--", "-").strip("-")
        if stem
        else f"{date_part}-{suffix}"
    )


def story_heat(members: list[Candidate], occurred: datetime | None, now: datetime) -> float:
    """Heat for a whole event.

    Same shape as the per-item score in heat.py, but the independent-source term
    is now real rather than approximated, which is the entire point of M3.
    """
    from ahr.processing.heat import CONTENT_TYPE_WEIGHT, UNKNOWN_TYPE_WEIGHT, freshness_decay

    primary = min(members, key=primary_rank)
    age_hours = (now - occurred).total_seconds() / 3600.0 if occurred else 0.0
    tier_bonus = {"primary": 30.0, "expert": 18.0, "secondary": 12.0}.get(primary.source_tier, 6.0)
    sources = independent_sources(members)
    quality = max((m.quality_score or 50.0) for m in members)
    type_weight = CONTENT_TYPE_WEIGHT.get(primary.content_type or "", UNKNOWN_TYPE_WEIGHT)

    base = tier_bonus + math.log1p(max(sources - 1, 0)) * 20.0 + quality * 0.15
    return round(freshness_decay(age_hours) * type_weight * base, 3)

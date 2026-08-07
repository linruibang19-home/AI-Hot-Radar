"""Answer generation with verifiable citations (M4).

AHR-RAG-400 §9–§10 and the locked constraint that LLM output is not a trusted
fact shape everything here:

* evidence is numbered `[E1]…[En]` and the model may only cite those numbers;
* the server resolves every number back to a real `content_chunk` row — the
  frontend never sees a URL the model produced;
* an answer with no supported evidence is a refusal, not a guess.

The B1 baseline settled how refusal must work. Retrieval similarity cannot
decide it: the highest-scoring unanswerable question ("llama.cpp b10999 版本修了
什么" — the corpus holds b10211 through b10240) scored **0.7205**, above the
mean for answerable ones. So the decision is made here, from whether the model
could ground its claims, not from a distance threshold upstream.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ahr.rag.parent import PARENT_BUDGET_TOKENS
from ahr.rag.planner import RetrievalPlan

# Evidence beyond this is unlikely to be read and crowds the prompt.
# AHR-RAG-400 §8: final evidence is 6-12 passages.
MAX_EVIDENCE = 10

# Per-passage cap. A whole long article as one citation makes the claim
# impossible to check against a specific sentence.
MAX_EVIDENCE_CHARS = 1200

# Cap once a passage has been widened to its parent block (B5).
#
# Derived from the ladder's token budget rather than picked separately. Set
# independently at 4000 it silently truncated exactly the tier the ladder had
# just decided *did* fit — a 2000-token document runs to roughly 6000 characters,
# so tier ① was chosen and then cut back to two thirds of itself.
#
# ~3 characters per token is the blended rate for this corpus: chunking.py
# counts CJK at 1.5 and Latin at 4, and the bodies are mixed.
CHARS_PER_TOKEN = 3
MAX_PARENT_CHARS = PARENT_BUDGET_TOKENS * CHARS_PER_TOKEN

# v2 adds the answer-shape rules. v1 said what was forbidden but never said what
# a good answer looks like, and the model settled on the safest thing that
# satisfied every prohibition: an undifferentiated bullet list of whatever the
# evidence contained. Asking "最近 Codex 有什么消息" returned eleven bullets, five
# of them about other companies, with no sentence anywhere saying what the answer
# *was*. Nothing in v1 was violated — the reader simply had to do the summarising
# the assistant was there to do.
ANSWER_PROMPT_VERSION = "rag-answer-v2"

_CITATION_RE = re.compile(r"\[E(\d+)\]")

# Bare evidence labels, including ranges: `E3`, `E6-E10`, `E6–E10`.
_BARE_LABEL_RE = re.compile(r"\bE\d+(?:\s*[-–—~]\s*E?\d+)?")

SYSTEM_PROMPT = """你是 AI Hot Radar 的问答助手，只依据给定证据回答。

## 回答结构（必须遵守）

**第一段必须是直接回答，不带任何列表符号。** 用 1-3 句话给出结论：
问什么答什么，把最重要的事实放在最前面。读者只读这一段也应该拿到答案。

结论之后，如果还有值得展开的内容，再用 `- ` 列点补充细节。
只有一两条事实时不要用列表，直接写成段落。

如果证据里同时有**直接相关**和**间接相关**的内容，先写直接相关的；
间接的另起一段并说明它为什么只是间接相关，不要混在同一个列表里。

关键结论里的核心事实（数字、型号、版本号、结论词）用 `**加粗**` 标出，
每段最多加粗一处——到处加粗等于没有重点。

## 硬规则

1. 每一个可核实的事实陈述后面必须紧跟证据编号，格式 [E1]、[E2]。
2. 只能使用给定的证据编号，不得编造编号，不得引用未提供的来源。
3. 证据里没有的内容一律不要写。宁可说"检索到的内容里没有提到"，也不要推测。
4. 如果证据完全不足以回答，把 answer_markdown 留空，并在 limitations 里说明缺什么。
5. 证据之间互相矛盾时，如实指出分歧和各自的来源，不要挑一个当定论。
6. 不要输出证据原文的大段复制，用自己的话概括并标注编号。
7. **不要在 limitations 里写证据编号**，那是给正文用的。

只输出 JSON：
{"answer_markdown": "...", "claims": [{"text": "...", "evidence_ids": ["E1"],
 "certainty": "confirmed|likely|uncertain"}], "limitations": ["..."]}"""


@dataclass
class Evidence:
    """One numbered passage handed to the model."""

    number: int
    chunk_id: str
    content_item_id: str
    title: str
    source_name: str
    source_tier: str
    published_at: datetime | None
    canonical_url: str
    text: str
    # M3 already computed these; the answer is where they finally matter. A
    # reader deciding whether to believe a claim wants to know it came from the
    # vendor rather than a blog, and that three unrelated outlets carried it.
    story_slug: str | None = None
    independent_sources: int = 1

    @property
    def label(self) -> str:
        return f"E{self.number}"


@dataclass
class Citation:
    number: int
    chunk_id: str
    content_item_id: str
    claim_text: str
    title: str
    source_name: str
    canonical_url: str
    published_at: datetime | None
    source_tier: str = "secondary"
    story_slug: str | None = None
    independent_sources: int = 1
    # Filled after generation by `support.score_citations`. None means "not
    # scored" — a reranker outage must not render as "unsupported".
    support_score: float | None = None


@dataclass
class Answer:
    question: str
    answer_markdown: str
    citations: list[Citation]
    limitations: list[str] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None
    plan: RetrievalPlan | None = None
    model: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    # What retrieval actually put in front of the model, cited or not. A refusal
    # that only says "not enough evidence" gives the reader nowhere to go, while
    # the system knows exactly what it looked at — and seeing that the window
    # caught the wrong week is usually enough for them to fix the question.
    considered: list[dict[str, Any]] = field(default_factory=list)
    # Set by `_persist`. The row was always written; without the id reaching the
    # client there was no way to read a conversation back, so every answer died
    # with the page that displayed it.
    query_id: str | None = None
    asked_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "queryId": self.query_id,
            "askedAt": self.asked_at.isoformat() if self.asked_at else None,
            "question": self.question,
            "answerMarkdown": self.answer_markdown,
            "refused": self.refused,
            "refusalReason": self.refusal_reason,
            "limitations": self.limitations,
            "citations": [
                {
                    "number": c.number,
                    "chunkId": c.chunk_id,
                    "itemId": c.content_item_id,
                    "claim": c.claim_text,
                    "title": c.title,
                    "sourceName": c.source_name,
                    "url": c.canonical_url,
                    "publishedAt": c.published_at.isoformat() if c.published_at else None,
                    "sourceTier": c.source_tier,
                    "storySlug": c.story_slug,
                    "independentSources": c.independent_sources,
                    "supportScore": c.support_score,
                }
                for c in self.citations
            ],
            "plan": self.plan.as_dict() if self.plan else None,
            "model": self.model,
            "metrics": self.metrics,
            "considered": self.considered,
        }


def summarise_considered(evidence: list[Evidence]) -> list[dict[str, Any]]:
    """One row per distinct document the model was shown."""
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in evidence:
        if item.content_item_id in seen:
            continue
        seen.add(item.content_item_id)
        rows.append(
            {
                "itemId": item.content_item_id,
                "title": item.title,
                "sourceName": item.source_name,
                "sourceTier": item.source_tier,
                "publishedAt": item.published_at.isoformat() if item.published_at else None,
            }
        )
    return rows


def load_evidence(
    connection: Any,
    chunk_ids: list[str],
    *,
    limit: int = MAX_EVIDENCE,
) -> list[Evidence]:
    """Turn ranked chunk ids into numbered, attributable evidence.

    `body_text` is used verbatim. The context header that `context.py` prepends
    for embedding is deliberately absent: a citation has to be checkable against
    the original document, and synthesised text is not in it.
    """
    if not chunk_ids:
        return []

    wanted = chunk_ids[:limit]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ch.id::text, ci.id::text, ch.body_text,
                   COALESCE(ci.zh_title, ci.title), s.name, s.source_tier,
                   COALESCE(ci.published_at, ci.observed_at), ci.canonical_url,
                   st.slug, COALESCE(st.independent_source_count, 1)
              FROM content_chunk ch
              JOIN content_revision cr ON cr.id = ch.content_revision_id
              JOIN content_item ci ON ci.id = cr.content_item_id
              JOIN source s ON s.id = ci.source_id
              LEFT JOIN story st ON st.id = ci.story_id
             WHERE ch.id = ANY(%s::uuid[])
            """,
            (wanted,),
        )
        rows = {row[0]: row for row in cursor.fetchall()}

    # Ranked order, not database order: the number a passage gets is its rank,
    # and the model reads the first ones most carefully.
    evidence: list[Evidence] = []
    for chunk_id in wanted:
        row = rows.get(chunk_id)
        if row is None:
            continue
        evidence.append(
            Evidence(
                number=len(evidence) + 1,
                chunk_id=row[0],
                content_item_id=row[1],
                text=(row[2] or "")[:MAX_EVIDENCE_CHARS],
                title=row[3] or "",
                source_name=row[4] or "",
                source_tier=row[5] or "",
                published_at=row[6],
                canonical_url=row[7] or "",
                story_slug=row[8],
                independent_sources=int(row[9] or 1),
            )
        )
    return evidence


def build_user_prompt(question: str, evidence: list[Evidence], plan: RetrievalPlan) -> str:
    """Assemble the prompt: the question, the resolved time window, the evidence."""
    lines = [f"问题：{question}", ""]

    if plan.time_range is not None:
        window = plan.time_range
        lines.append(
            f"检索时间范围：{window.start.date()} 至 {window.end.date()}"
            f"（{window.label}）。回答开头请说明这个范围。"
        )
        lines.append("")

    lines.append("证据：")
    for item in evidence:
        published = item.published_at.date().isoformat() if item.published_at else "日期未知"
        lines.append(
            f"\n[{item.label}] {item.title}\n"
            f"来源：{item.source_name}（{item.source_tier}）· {published}\n"
            f"{item.text}"
        )
    return "\n".join(lines)


def parse_model_output(raw: str) -> dict[str, Any]:
    """Read the model's JSON, tolerating a fenced code block or no JSON at all.

    The envelope is a transport detail, and treating a deviation from it as
    "the model produced nothing" was throwing away finished answers. Measured
    on the 08-07 generation run: of six answerable questions scored as
    refusals, two were the model replying in plain markdown — correctly
    written, `[E1][E2]` markers in place — which `json.loads` rejected, leaving
    an empty `answer_markdown` and therefore a refusal. The reader was told the
    corpus had nothing on a question the corpus had answered.

    So a bare answer is recovered rather than discarded, under two conditions
    that keep it from recovering garbage:

    * the text must not look like JSON — a truncated `{"answer_markdown": "…`
      is a different failure and must not be shown as prose;
    * it must carry at least one `[En]` marker, which is the only evidence
      available here that the model was answering from the evidence at all.

    Nothing about verification is relaxed: the recovered text goes through the
    same `bind_citations`, so every number is still resolved against the real
    evidence set and invented ones are still stripped.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _recover_bare_answer(text)
    if isinstance(parsed, dict):
        return parsed
    # Valid JSON, wrong shape. A bare JSON string is the answer with quotes
    # around it, so recover from the decoded value rather than from `text` —
    # otherwise the quotes are rendered as part of the answer.
    return _recover_bare_answer(parsed if isinstance(parsed, str) else text)


def _recover_bare_answer(text: str) -> dict[str, Any]:
    if text.startswith(("{", "[")) or not _CITATION_RE.search(text):
        return {"answer_markdown": "", "claims": [], "limitations": ["模型输出无法解析为 JSON"]}
    return {
        "answer_markdown": text,
        "claims": [],
        # Recorded rather than silently swallowed: a rising count here means
        # the prompt contract is losing its grip on the model.
        "limitations": ["模型未按约定输出 JSON，已按正文解析并照常校验引用"],
    }


def _claim_evidence(claims: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """Every `(evidence number, claim text)` the model declared, in order.

    The model writes the ids both ways — `"E1"` and `1` — so both are accepted.
    """
    pairs: list[tuple[int, str]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text", "")).strip()
        for raw_id in claim.get("evidence_ids") or []:
            parsed = re.fullmatch(r"E?(\d+)", str(raw_id).strip())
            if parsed:
                pairs.append((int(parsed.group(1)), text))
    return pairs


def bind_citations(
    answer_markdown: str,
    claims: list[dict[str, Any]],
    evidence: list[Evidence],
    limitations: list[str] | None = None,
) -> tuple[str, list[Citation], list[str], list[str]]:
    """Resolve every `[En]` to a real passage, and drop the ones that are not.

    A number the model invented is removed from the text rather than rendered:
    AHR-API-500 §4 requires the server to resolve citations before they reach
    the client, precisely so a fabricated reference cannot be displayed as a
    source. Returns the cleaned text, the bound citations, and what was dropped.

    When the prose carries no resolvable marker at all, the grounding is taken
    from `claims[].evidence_ids` instead — see the comment on that branch. The
    resolution rules are identical either way.
    """
    by_number = {item.number: item for item in evidence}
    problems: list[str] = []
    recovered: list[str] = []
    used: list[int] = []

    def note(number: int) -> None:
        if number in by_number:
            if number not in used:
                used.append(number)
        elif f"E{number}" not in problems:
            problems.append(f"E{number}")

    for match in _CITATION_RE.finditer(answer_markdown):
        note(int(match.group(1)))

    if not used and claims:
        # The model grounded its claims but wrote the prose without inline
        # markers — the `claims` array is where the contract asks for the
        # evidence ids, and it filled it. Reading only the prose meant an
        # answer whose every claim carried evidence was published as "the
        # corpus has nothing on this". Seen on RAG-GOLD-088, where four claims
        # named six passages and the bound citation count was zero.
        #
        # Only when the prose has *no* resolvable marker at all. Where the
        # model did anchor its citations, that is the more precise signal and
        # topping it up from `claims` would attach sources to sentences the
        # model never tied them to.
        for number, _ in _claim_evidence(claims):
            note(number)
        if used:
            recovered.append("模型未在正文中标注引用编号，下列来源取自它给出的 claims")

    # Renumber to the order they appear, so the reader sees [1][2][3] rather
    # than the retrieval ranks, which mean nothing to them.
    renumber = {original: index + 1 for index, original in enumerate(used)}

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if number in renumber:
            return f"[{renumber[number]}]"
        return ""  # dangling reference: strip it rather than show it

    cleaned = _CITATION_RE.sub(replace, answer_markdown)

    # The same treatment for anything else the model wrote for the reader.
    # `limitations` was going out untouched, so a raw `[E1]` reached the page —
    # the model's own labelling, in a product whose claim is that every visible
    # reference was resolved server-side. Same rule as the body: renumber what
    # resolves, delete what does not.
    def renumber_text(text: str) -> str:
        return _CITATION_RE.sub(replace, text).strip()

    def clean_limitation(text: str) -> str:
        """Bracketed labels renumber; bare ones are removed.

        The model writes `[E1]` in the body and, despite being told not to,
        bare `E3、E6-E10` in the limitations — a form the bracket pattern never
        matched. Both are its private numbering, and neither means anything to a
        reader looking at a list numbered [1]..[n]. Confined to limitations: in
        the body a bare `E5` could plausibly be part of a model name.
        """
        cleaned = renumber_text(text)
        cleaned = _BARE_LABEL_RE.sub("", cleaned)
        # Tidy the punctuation the removal leaves behind: "（如 、）", "（）".
        cleaned = re.sub(r"[（(]\s*[、,，\-–—\s]*\s*[)）]", "", cleaned)
        cleaned = re.sub(r"[、,，]\s*(?=[)）])", "", cleaned)
        return cleaned.strip(" 、,，")

    claim_for: dict[int, str] = {}
    for number, text in _claim_evidence(claims):
        if number in renumber and number not in claim_for:
            claim_for[number] = text

    citations = [
        Citation(
            number=renumber[original],
            chunk_id=by_number[original].chunk_id,
            content_item_id=by_number[original].content_item_id,
            claim_text=claim_for.get(original, ""),
            title=by_number[original].title,
            source_name=by_number[original].source_name,
            canonical_url=by_number[original].canonical_url,
            published_at=by_number[original].published_at,
            source_tier=by_number[original].source_tier or "secondary",
            story_slug=by_number[original].story_slug,
            independent_sources=by_number[original].independent_sources,
        )
        for original in used
    ]
    cleaned_limitations = [
        stripped for text in (limitations or []) if (stripped := clean_limitation(text))
    ]
    return cleaned.strip(), citations, problems, [*cleaned_limitations, *recovered]


def check_invariants(
    answer_markdown: str,
    citations: list[Citation],
    evidence: list[Evidence],
    *,
    refused: bool,
) -> list[str]:
    """The four hard assertions from the evaluation plan.

    These are checks, not aspirations — a violation means the answer is not
    publishable, and the caller turns it into a refusal.
    """
    violations: list[str] = []
    numbers = {c.number for c in citations}

    for match in re.finditer(r"\[(\d+)\]", answer_markdown):
        if int(match.group(1)) not in numbers:
            violations.append(f"答案中的 [{match.group(1)}] 没有对应的引用记录")
            break

    known_chunks = {item.chunk_id for item in evidence}
    for citation in citations:
        if citation.chunk_id not in known_chunks:
            violations.append(f"引用 [{citation.number}] 指向本次证据集之外的分块")
            break

    if not refused and not citations:
        violations.append("回答没有任何引用，必须标记为拒答")

    if not refused and not answer_markdown.strip():
        violations.append("回答为空但未标记为拒答")

    return violations

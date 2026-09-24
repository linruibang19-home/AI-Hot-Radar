"""A citation points at the sibling that says its claim, and only when the hit does not."""

from __future__ import annotations

import asyncio
import inspect

from ahr.rag import service
from ahr.rag.anchor import Siblings, choose_anchors, pick_anchor, visible_siblings
from ahr.rag.answer import Citation
from ahr.rag.parent import ParentBlock
from ahr.rag.rerank import RerankUnavailableError

THRESHOLD = 0.30


def _parent(tier: str, texts: list[str]) -> ParentBlock:
    ids = tuple(f"c{i}" for i in range(len(texts)))
    return ParentBlock(
        chunk_id="c1",
        revision_id="r",
        tier=tier,
        text="\n\n".join(texts),
        token_count=0,
        chunk_ids=ids,
        chunk_texts=tuple(texts),
    )


def _citation(chunk_id: str, claim: str = "API 价格打 8 折。") -> Citation:
    return Citation(
        number=1,
        chunk_id=chunk_id,
        content_item_id="item",
        claim_text=claim,
        title="t",
        source_name="量子位",
        canonical_url="https://example.com",
        published_at=None,
    )


class _Reranker:
    def __init__(self, scores: list[float] | None) -> None:
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int
    ) -> list[tuple[int, float]]:
        self.calls.append((query, documents))
        if self.scores is None:
            raise RerankUnavailableError("down")
        return sorted(enumerate(self.scores), key=lambda pair: -pair[1])[:top_n]


def test_document_and_section_tiers_offer_their_siblings() -> None:
    for tier in ("document", "section"):
        block = visible_siblings(_parent(tier, ["标题：价格打 8 折", "正文"]), max_chars=6000)
        assert block == Siblings(chunk_ids=("c0", "c1"), texts=("标题：价格打 8 折", "正文"))


def test_neighbours_keep_their_hit() -> None:
    """Each neighbour has its own window; moving would change what the gate judged."""
    assert visible_siblings(_parent("neighbours", ["a", "b", "c"]), max_chars=6000) is None


def test_a_single_chunk_has_nowhere_to_move() -> None:
    assert visible_siblings(_parent("document", ["only"]), max_chars=6000) is None


def test_chunks_past_the_prompt_cut_are_not_candidates() -> None:
    """The model read `parent.text[:max_chars]`; nothing after it can be a source."""
    block = visible_siblings(_parent("document", ["aaaa", "bbbb", "cccc"]), max_chars=8)
    # "aaaa" + "\n\n" = 6 characters, so two of "bbbb" are visible and "cccc" is not.
    assert block == Siblings(chunk_ids=("c0", "c1"), texts=("aaaa", "bb"))


def test_a_hit_that_supports_its_claim_stays() -> None:
    assert pick_anchor("c1", ("c0", "c1"), {0: 0.99, 1: 0.45}, threshold=THRESHOLD) is None


def test_an_unsupported_hit_moves_to_the_sibling_that_says_it() -> None:
    """The production case: the price is in the headline chunk, not the hit."""
    assert pick_anchor("c1", ("c0", "c1"), {0: 0.97, 1: 0.02}, threshold=THRESHOLD) == "c0"


def test_no_better_sibling_means_no_move() -> None:
    assert pick_anchor("c1", ("c0", "c1"), {0: 0.01, 1: 0.02}, threshold=THRESHOLD) is None


def test_a_hit_cut_from_view_counts_as_failing() -> None:
    assert pick_anchor("c9", ("c0", "c1"), {0: 0.2, 1: 0.6}, threshold=THRESHOLD) == "c1"


def test_moves_are_keyed_by_the_hit() -> None:
    reranker = _Reranker([0.97, 0.02])
    siblings = {"c1": Siblings(chunk_ids=("c0", "c1"), texts=("价格打 8 折", "正文"))}
    moved = asyncio.run(
        choose_anchors(reranker, [_citation("c1")], siblings, threshold=THRESHOLD)  # type: ignore[arg-type]
    )
    assert moved == {"c1": "c0"}
    assert reranker.calls == [("API 价格打 8 折。", ["价格打 8 折", "正文"])]


def test_an_outage_moves_nothing() -> None:
    siblings = {"c1": Siblings(chunk_ids=("c0", "c1"), texts=("a", "b"))}
    moved = asyncio.run(
        choose_anchors(_Reranker(None), [_citation("c1")], siblings, threshold=THRESHOLD)  # type: ignore[arg-type]
    )
    assert moved == {}


def test_citations_without_siblings_cost_no_request() -> None:
    reranker = _Reranker([0.9])
    moved = asyncio.run(choose_anchors(reranker, [_citation("c1")], {}, threshold=THRESHOLD))  # type: ignore[arg-type]
    assert moved == {} and reranker.calls == []


def test_the_trace_still_marks_what_retrieval_found() -> None:
    """The anchor is for the reader; the trace explains retrieval, which found the hit."""
    source = inspect.getsource(service.answer_question)
    assert "trace.mark_cited(cited_hits)" in source
    assert source.index("cited_hits = ") < source.index("load_chunk_excerpts(")

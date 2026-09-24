"""Published sentences and the markers they carry — the pairs a reader checks."""

from __future__ import annotations

from ahr.rag.answer import drop_uncited_sentences
from ahr.rag.sentence_support import CitedSentence, cited_sentences

ANSWER = (
    "智谱完成约 50 亿美元融资。[1] 其中约六成投向 GLM 研发。[1][2]\n"
    "\n"
    "- 阶跃星辰发布 Step 5 Preview。[2]\n"
    "- 本周没有其他发布。"
)


def test_sentences_carry_their_distinct_markers_in_reading_order() -> None:
    assert cited_sentences(ANSWER) == [
        CitedSentence((0, 0), "智谱完成约 50 亿美元融资。", (1,)),
        CitedSentence((0, 1), "其中约六成投向 GLM 研发。", (1, 2)),
        CitedSentence((2, 0), "阶跃星辰发布 Step 5 Preview。", (2,)),
    ]


def test_a_repeated_marker_is_one_pair() -> None:
    assert cited_sentences("同一来源说了两次。[3][3]")[0].numbers == (3,)


def test_the_split_matches_the_publication_gate() -> None:
    """Every sentence here survives `drop_uncited_sentences`; the uncited one does not."""
    kept, removed, dropped = drop_uncited_sentences(ANSWER)
    assert dropped == ["本周没有其他发布。"]
    assert [s.text for s in cited_sentences(kept)] == [s.text for s in cited_sentences(ANSWER)]

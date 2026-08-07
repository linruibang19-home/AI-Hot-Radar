"""Streaming the answer without ever retracting it.

The property under test is *agreement*: whatever the reader watches arrive must
be character-for-character what the server ends up storing. A stream that drifts
from `bind_citations` would be a second, unverified rendering of the answer —
which is the thing AHR-API-500 §4 forbids, just moved to a different place.

The second property is the one that made token streaming look impossible: an
answer with no citations must be a refusal, and a refusal must never be preceded
by prose the reader already read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ahr.rag.answer import Evidence, bind_citations
from ahr.rag.incremental import AnswerStream, JsonStringExtractor


def _evidence(count: int = 3) -> list[Evidence]:
    return [
        Evidence(
            number=n,
            chunk_id=f"chunk-{n}",
            content_item_id=f"item-{n}",
            title=f"标题 {n}",
            source_name="Hugging Face Blog",
            source_tier="primary",
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
            canonical_url=f"https://example.com/{n}",
            text="…",
        )
        for n in range(1, count + 1)
    ]


def _stream(chunks: list[str], evidence: list[Evidence] | None = None) -> str:
    stream = AnswerStream(evidence or _evidence())
    out = "".join(stream.feed(chunk) for chunk in chunks)
    return out + stream.finish()


# --- agreement with the stored answer --------------------------------------

ANSWERS = [
    "使用 MXFP4 量化的是 **Kimi K3**[E1]。",
    "第一段结论[E2]。\n\n- 细节一[E1]\n- 细节二[E3]",
    "多个引用连在一起[E1][E2][E3]，然后继续。",
    "同一个来源被引用两次[E2]，后面再引一次[E2]。",
    "引用顺序不是证据顺序[E3] 然后 [E1]。",
]


@pytest.mark.parametrize("answer", ANSWERS)
@pytest.mark.parametrize("size", [1, 3, 7, 1000])
def test_the_stream_matches_what_gets_stored(answer: str, size: int) -> None:
    """The whole point. Split the same answer at every plausible boundary and it
    must always assemble into exactly what `bind_citations` produces."""
    evidence = _evidence()
    chunks = [answer[i : i + size] for i in range(0, len(answer), size)]

    stored, _, _, _ = bind_citations(answer, [], evidence)
    assert _stream(chunks, evidence) == stored


def test_a_marker_split_across_deltas_is_not_shown_broken() -> None:
    """`[E` arriving at the end of one delta and `1]` at the start of the next.
    Emitting the fragment would put a stray bracket on screen and then need to
    take it back — one character, but the same category of defect."""
    evidence = _evidence()
    text = _stream(["答案是 Kimi K3[E", "1]，就这样。"], evidence)

    assert text == "答案是 Kimi K3[1]，就这样。"
    assert "[E" not in text


def test_an_invented_citation_number_never_appears() -> None:
    """The model cited E9 with three passages in front of it. §4 exists so that
    a fabricated source cannot be displayed — not so it can be corrected later."""
    evidence = _evidence(3)
    text = _stream(["有证据支持[E1]，这句是编的[E9]。"], evidence)

    assert text == "有证据支持[1]，这句是编的。"
    assert "9" not in text


def test_numbering_follows_reading_order_not_retrieval_rank() -> None:
    """A reader sees [1][2][3] in the order they appear; the retrieval ranks
    that produced E3 and E1 mean nothing to them."""
    assert _stream(["先引用第三条[E3]，再引用第一条[E1]。"]) == "先引用第三条[1]，再引用第一条[2]。"


# --- nothing is released that could be retracted ---------------------------


def test_nothing_is_emitted_before_the_first_resolved_citation() -> None:
    """The invariant that made this look impossible. Until one citation resolves
    the answer could still turn out to be a refusal, so the prose waits."""
    stream = AnswerStream(_evidence())

    assert stream.feed("这是一段还没有引用的开头文字，") == ""
    assert stream.feed("再来一句还是没有引用。") == ""

    released = stream.feed("现在有了[E1]。")
    assert released.startswith("这是一段还没有引用的开头文字")
    assert released.endswith("现在有了[1]。")


def test_an_answer_that_never_cites_anything_shows_nothing_at_all() -> None:
    """It will be stored as a refusal. Had any of it been streamed, the refusal
    would be a retraction of paragraphs already read."""
    stream = AnswerStream(_evidence())

    assert stream.feed("模型凭常识写了一整段，") == ""
    assert stream.feed("但一个证据编号也没引。") == ""
    assert stream.finish() == ""
    assert stream.citation_count == 0


def test_an_answer_citing_only_invented_numbers_shows_nothing() -> None:
    """Same case wearing a disguise: markers are present, none resolve, so the
    stored answer has zero citations and is a refusal."""
    stream = AnswerStream(_evidence(2))

    assert stream.feed("看起来有来源[E7]，其实没有[E8]。") == ""
    assert stream.finish() == ""


def test_the_release_trims_leading_space_like_the_stored_answer_does() -> None:
    """`bind_citations` strips the finished string. Without the same treatment
    the streamed copy would start with whitespace the stored one does not."""
    evidence = _evidence()
    answer = "\n  开头有空白[E1]。"

    stored, _, _, _ = bind_citations(answer, [], evidence)
    assert _stream([answer], evidence) == stored


def test_a_trailing_partial_marker_is_flushed_at_the_end() -> None:
    """A truncated response can end mid-marker. It was never a marker, and
    holding it forever would silently drop the last characters."""
    stream = AnswerStream(_evidence())
    stream.feed("有引用[E1]，然后被截断了[E")

    assert stream.finish() == "[E"


# --- pulling the prose out of the JSON response ----------------------------


def test_the_prose_field_is_extracted_as_it_arrives() -> None:
    extractor = JsonStringExtractor("answer_markdown")
    out = "".join(
        extractor.feed(piece)
        for piece in ['{"claims": [], "answer_mark', 'down": "答案正文', '在这里"}']
    )
    assert out == "答案正文在这里"


def test_other_fields_are_not_mistaken_for_the_answer() -> None:
    extractor = JsonStringExtractor("answer_markdown")
    out = "".join(
        extractor.feed(piece)
        for piece in ['{"limitations": ["缺少 X"], ', '"answer_markdown": "真正的答案"}']
    )
    assert out == "真正的答案"


def test_escapes_are_decoded() -> None:
    extractor = JsonStringExtractor("answer_markdown")
    out = extractor.feed('{"answer_markdown": "第一行\\n第二行 \\"引号\\" 与反斜杠 \\\\"}')
    assert out == '第一行\n第二行 "引号" 与反斜杠 \\'


def test_an_escape_split_across_deltas_survives() -> None:
    """A `\\` can be the last character of one chunk and `n` the first of the
    next. Handling each chunk independently would emit a literal backslash."""
    extractor = JsonStringExtractor("answer_markdown")
    out = "".join(extractor.feed(piece) for piece in ['{"answer_markdown": "第一行\\', 'n第二行"}'])
    assert out == "第一行\n第二行"


def test_a_unicode_escape_split_across_deltas_survives() -> None:
    extractor = JsonStringExtractor("answer_markdown")
    out = "".join(extractor.feed(piece) for piece in ['{"answer_markdown": "\\u4e2d\\u65', '87"}'])
    assert out == "中文"


def test_an_escaped_quote_does_not_end_the_value() -> None:
    extractor = JsonStringExtractor("answer_markdown")
    out = extractor.feed('{"answer_markdown": "他说\\"你好\\"，然后继续"}')
    assert out == '他说"你好"，然后继续'


def test_the_closing_quote_ends_extraction() -> None:
    """Anything after the value belongs to other fields and must not leak into
    the answer the reader is watching."""
    extractor = JsonStringExtractor("answer_markdown")
    first = extractor.feed('{"answer_markdown": "答案", "limitations": ["不该出现"]}')
    assert first == "答案"
    assert extractor.feed('{"more": "也不该出现"}') == ""

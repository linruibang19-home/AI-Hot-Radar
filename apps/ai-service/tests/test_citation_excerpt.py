"""A citation carries the passage it stands on, not only the claim it supports.

`claim_text` is the sentence *the model* wrote. It was, until now, the only
per-citation text reaching the browser — so a reader hovering a citation to
check a fact was shown the model's own restatement of that fact, presented in
the position where a source quote belongs. Checking the model against itself is
the one verification that cannot fail, which makes it worthless.

`excerpt` is `content_chunk.body_text`, verbatim.
"""

from __future__ import annotations

import inspect

from ahr.rag import answer as answer_module
from ahr.rag import retrieval, service


def test_the_excerpt_is_the_stored_text_not_the_indexing_header() -> None:
    """`load_chunk_texts` prepends the title, source and date the bi-encoder saw
    at index time. That is right for ranking and wrong here: a reader checking a
    quote would be shown a header this system composed as the source's words."""
    source = inspect.getsource(retrieval.load_chunk_excerpts)
    assert "build_embedding_text" not in source
    assert "left(body_text, %s)" in source


def test_both_paths_cut_the_excerpt_at_the_same_length() -> None:
    """The live answer and its own permalink quote the same passage. Two
    literals that agree today disagree after one of them is tuned, and this
    pair would drift silently."""
    assert f"left(ch.body_text, {retrieval.EXCERPT_CHARS})" in service._CONVERSATION_SELECT


def test_the_claim_and_the_excerpt_stay_separate_fields() -> None:
    """Collapsing them would restore exactly the defect: one text field whose
    provenance the reader cannot tell."""
    fields = answer_module.Citation.__dataclass_fields__
    assert "claim_text" in fields and "excerpt" in fields
    payload = inspect.getsource(answer_module.Answer.as_dict)
    assert '"claim": c.claim_text' in payload
    assert '"excerpt": c.excerpt' in payload


def test_excerpts_are_read_after_every_gate_that_can_empty_the_citations() -> None:
    """`check_invariants` and the credential policy both set `citations = []`.
    Loading text for citations about to be discarded is a query for nothing —
    and reading it earlier would have to survive being thrown away."""
    source = inspect.getsource(service.answer_question)
    loaded = source.index("load_chunk_excerpts(")
    assert source.index("check_invariants(") < loaded
    assert source.index("credential_blocked") < loaded


def test_a_replayed_answer_keeps_its_excerpts() -> None:
    """A cache hit *is* that answer. Rebuilding its citations without the
    excerpt would make the replay quietly less checkable than the original."""
    source = inspect.getsource(service)
    rebuild = source[source.index("claim_text=str(row.get(\"claim\")") :][:900]
    assert 'excerpt=str(row.get("excerpt") or "")' in rebuild

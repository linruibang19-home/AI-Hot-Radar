"""A refusal explains itself with what the model actually found.

Rule 3 of the answer prompt asks the model to write 「检索到的内容里没有提到 X」
rather than speculate, and it complies. That sentence is a statement about the
*absence* of evidence, so it cannot carry a `[n]` — nothing supports the claim
that nothing supports a claim — and `drop_uncited_sentences` removes it. The
answer then empties and the reader is handed 「检索到的内容不足以回答这个问题」
in place of the specific sentence the model had written for them.

It stays a refusal. Publishing an uncited sentence as an answer is the thing
this whole pipeline exists to prevent, and a scope statement is uncited by
construction. Only the *explanation* changes.

The risk being guarded is a real assertion riding inside a sentence that opens
like a scope statement — 「证据里没提到 X，不过 X 是 70B」 — which would put an
uncited claim on the page through the one door left open.
"""

from __future__ import annotations

import inspect

from ahr.rag import service
from ahr.rag.service import _scope_statement

FOUND = "检索到的内容里没有提到 LiteLLM 的 rc 版本和 dev 版本之间的具体区别。"
PARTIAL = "证据仅列出了 rc 版本的发布说明，未对两者进行对比。"


def test_a_plain_scope_statement_is_used() -> None:
    assert _scope_statement([FOUND]) == FOUND
    assert _scope_statement([PARTIAL]) == PARTIAL


def test_a_hedge_word_disqualifies_the_sentence() -> None:
    """「…，不过 X 是 70B」 opens as a scope statement and ends as a claim."""
    assert _scope_statement(["检索到的内容里没有提到 X，不过 X 的参数量很大。"]) is None
    assert _scope_statement(["证据中未提到该模型，但它已经发布。"]) is None


def test_a_digit_disqualifies_the_sentence() -> None:
    """A scope statement asserting a number is not a scope statement. The guard
    is deliberately blunt: it also rejects 「没有提到 gemma-4 的区别」 and falls
    back to the generic message, which is the safe direction to fail."""
    assert _scope_statement(["证据中未提到该模型，参数量 70B。"]) is None


def test_an_assertion_before_the_scope_clause_is_rejected() -> None:
    """Anchored to the start of the sentence, so nothing can be smuggled in
    front of the words that make it look like a scope statement."""
    assert _scope_statement(["该模型很快，证据里没有提到延迟。"]) is None


def test_an_ordinary_assertion_is_never_mistaken_for_one() -> None:
    assert _scope_statement(["Anthropic 发布了 MHS 预览。"]) is None
    assert _scope_statement([]) is None


def test_the_scope_statement_is_a_reason_never_an_answer() -> None:
    """It is uncited by construction. Reaching `answer_markdown` would publish
    exactly the sentence the gate removed, through the door opened to explain
    the removal."""
    source = inspect.getsource(service.answer_question)
    block = source[source.index("scope = _scope_statement(") :][:400]
    assert "refusal_reason = scope" in block
    assert "text = scope" not in block
    assert "answer_markdown" not in block
    # And only when nothing grounded survived, so it cannot overwrite the
    # reason on a refusal that had citations for some other failure.
    assert "if scope and not citations:" in block


def test_the_refusal_stays_a_refusal() -> None:
    """`over_refusal_rate` must not improve because the message got better. If
    the corpus really lacks the material, this is a correct refusal and should
    keep counting as one."""
    source = inspect.getsource(service.answer_question)
    decision = source.index("refused = not text or not citations")
    scope = source.index("scope = _scope_statement(")
    # The refusal is decided before the message is chosen, and nothing between
    # them sets `refused` back to False.
    assert decision < scope
    assert "refused = False" not in source[decision:scope]

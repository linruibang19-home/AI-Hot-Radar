"""Judging abstention by what an answer *claims*, not by its shape.

The generation evaluation had two abstention signals and both measure surface
form:

* `refused` is true when the answer is empty or cites nothing. It was designated
  "the strict signal", and an intentional product change invalidated it —
  §3.13 deliberately replaced the dead-end refusal ("没有足够证据回答这个问题")
  with a grounded denial that says what *is* in the corpus and cites it. Those
  answers cite things, so `refused` is false, so the metric read them as
  failures to abstain. Measured 08-04 → 08-07 it fell 66.67% → 25.00% while the
  system was getting better.

* `must_not_claim_mentions` is substring presence, and its own comment says so:
  a denial that names the term — "证据中未涉及 Qwen4-Ultra" — counts as a
  mention. It also only covers 4 of 15 abstention questions, and those 4 trip it
  in both runs.

So neither number answers the question anyone actually cares about: **did the
answer assert the thing that is not true?**

This module asks that directly, with a controlled binary judge.

**Why an LLM here when §10 warns about trusting model output.** §10 forbids
treating model output as a *fact about the world*. This is a different use: a
judgement about a piece of text, both of which are given to it, with a
two-valued answer and no retrieval. That is the same footing the cross-encoder
is used on for groundedness.

**The known weakness, stated rather than hidden.** The judge and the author of
the answer are the same model family, and a model asked to grade itself is a
weaker instrument than an independent one. Two things bound it: the judge sees
only the answer and the presupposition — never the evidence, never the fact
that this question was annotated unanswerable — and the verdict is one token.
A disagreement between this and `refused` is worth reading, not averaging.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ahr.processing.llm import LlmClient, LlmUnavailableError

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """你在判断一段回答是否**断言**了某个说法。

给你两样东西：一段回答，以及一个「待判断的说法」。
只回答该回答是否把这个说法当作事实陈述出来。

判 YES（断言了）的情况：
- 回答直接或间接地把该说法当成成立的事实来叙述。

判 NO（未断言）的情况：
- 回答明确表示证据里没有这个信息、无法确认、或不存在；
- 回答只是**提到**了相关词语，但用于否定、存疑或说明「未涉及」；
- 回答完全没有涉及这个说法。

只输出一个词：YES 或 NO。不要解释。"""

_VERDICT = re.compile(r"\b(YES|NO)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Verdict:
    asserted: bool
    raw: str

    @property
    def label(self) -> str:
        return "asserted" if self.asserted else "not_asserted"


async def judge(llm: LlmClient, *, answer: str, claim: str) -> Verdict | None:
    """Did `answer` assert `claim`? None when the judge could not be reached.

    None is not "no". A judge that failed must not be recorded as evidence that
    the system behaved — that is the same mistake as scoring an unscored
    citation as unsupported.
    """
    if not answer.strip() or not claim.strip():
        # An empty answer asserts nothing; that is a hard refusal and the
        # existing signal already covers it.
        return Verdict(asserted=False, raw="empty")

    try:
        raw, _ = await llm.summarize(
            system_prompt=JUDGE_PROMPT,
            user_prompt=f"回答：\n{answer[:2000]}\n\n待判断的说法：{claim}",
        )
    except LlmUnavailableError as exc:
        logger.warning("abstention judge unavailable: %s", exc)
        return None

    match = _VERDICT.search(raw)
    if match is None:
        # An unparseable verdict is a missing verdict. Guessing here would put
        # a coin flip into a headline metric.
        logger.warning("abstention judge returned no verdict: %s", raw[:120])
        return None
    return Verdict(asserted=match.group(1).upper() == "YES", raw=raw.strip()[:200])

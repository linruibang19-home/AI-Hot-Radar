"""`total_ms` has to cover every stage the reader waits for.

It did not. `total_ms` was stamped straight after generation, leaving the
support stage — a reranker round trip, median 2.3s — outside the number the
dashboard reports as end-to-end latency.

How it surfaced is the useful part: the stage shares on `/ops` summed to
**122.7%**. That looked like a presentation bug, and the first fix computed the
shares per request instead of dividing one median by another. It still summed
to 122.7%, because the arithmetic was never the problem — one stage was being
divided by a total that excluded it.
"""

from __future__ import annotations

import inspect

from ahr.rag import ops, service


def test_total_ms_is_stamped_after_the_support_stage() -> None:
    """The ordering *is* the correctness condition here."""
    source = inspect.getsource(service.answer_question)
    support_at = source.index('metrics["stages_ms"]["support"]')
    total_at = source.index('metrics["total_ms"]')

    assert support_at < total_at, "total_ms must be measured after support scoring"


def test_total_ms_is_not_also_set_earlier() -> None:
    """Two assignments would make the later one silently depend on the order of
    the dictionary update, which is how the first version drifted."""
    source = inspect.getsource(service.answer_question)
    assert source.count('"total_ms"') == 1


def test_the_stage_share_is_a_per_request_median() -> None:
    """A share of a whole must come from one request, not from dividing two
    medians computed over different populations — `support` is timed on the
    requests that had citations to score, `generate` on all of them."""
    source = inspect.getsource(ops.latency_summary)
    assert "total_ms" in source
    assert "NULLIF" in source, "guard against dividing by a zero total"


def test_no_percent_sign_survives_in_the_latency_sql() -> None:
    """psycopg scans the whole query string for placeholders, comments
    included. A `122.7%` written into a `--` comment raised "only '%s', '%b',
    '%t' are allowed as placeholders" — and the first attempt to document that
    re-triggered it by quoting the characters inside the same string.
    """
    source = inspect.getsource(ops.latency_summary)
    for block in source.split('"""')[1::2]:
        stray = [part for part in block.split("%") if not part.startswith(("s", "b", "t"))]
        # The split leaves one leading fragment that is not a placeholder.
        assert len(stray) <= 1, f"unescaped percent in SQL: {block[:80]}"

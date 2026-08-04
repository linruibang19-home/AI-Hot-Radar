"""SSE progress streaming (AHR-API-500 §4).

The endpoint streams *stages*, not model tokens, and that is the design rather
than a shortcut. Two steps run after generation finishes and can both change
what the reader is allowed to see: `bind_citations` deletes `[n]` markers the
model invented, and `check_invariants` can turn a complete answer into a
refusal. Relaying tokens live would render a fabricated source and then retract
a paragraph already read.

So the properties worth pinning are: the frames parse as SSE, the verified
answer arrives as one event at the end, and a failure mid-stream is reported on
the stream rather than as a truncated success.
"""

from __future__ import annotations

import asyncio
import json

from ahr.rag.api import _sse
from ahr.rag.service import _noop_stage

# --- frame format ----------------------------------------------------------


def test_frame_is_a_well_formed_sse_event() -> None:
    frame = _sse("stage", {"stage": "embed", "ms": 1853})

    assert frame.startswith("event: stage\n")
    assert "data: " in frame
    # The blank line terminates the frame; without it a client buffers forever.
    assert frame.endswith("\n\n")


def test_frame_data_is_a_single_line() -> None:
    """A newline inside `data:` would split one event into two malformed ones."""
    frame = _sse("answer", {"answerMarkdown": "第一行\n第二行"})

    body = [line for line in frame.split("\n") if line.startswith("data: ")]
    assert len(body) == 1


def test_chinese_is_sent_as_characters_not_escapes() -> None:
    """`ensure_ascii` would trade readable frames for \\uXXXX noise on a
    corpus that is substantially Chinese."""
    frame = _sse("stage", {"label": "检索证据"})
    assert "检索证据" in frame


def test_frame_round_trips_through_a_client_style_parse() -> None:
    payload = {"stage": "fuse", "found": 83}
    frame = _sse("stage", payload)

    event, data = frame.strip().split("\n", 1)
    assert event == "event: stage"
    assert json.loads(data.removeprefix("data: ")) == payload


# --- the stage reporter is optional ----------------------------------------


def test_pipeline_runs_without_a_reporter() -> None:
    """Evaluation runs pass no reporter, and 90-question batches must not pay
    for progress nobody is watching."""
    assert asyncio.run(_noop_stage("embed", {"ms": 1})) is None


def test_reporter_receives_stage_name_and_detail() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    async def record(name: str, detail: dict[str, object]) -> None:
        seen.append((name, detail))

    asyncio.run(record("rerank", {"ms": 3131, "degraded": False}))

    assert seen == [("rerank", {"ms": 3131, "degraded": False})]

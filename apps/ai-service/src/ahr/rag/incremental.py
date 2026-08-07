"""Streaming an answer without ever showing something that gets retracted.

`AHR-API-500` §4 requires the server to resolve citations before delivery, and
the note on `api.py` recorded token streaming as blocked on a prompt-contract
change. Working through it, most of that blocker turned out not to exist:

* **Renumbering is already left-to-right.** `bind_citations` numbers markers in
  order of first appearance, so the number a marker gets depends only on the
  text before it. No lookahead.
* **The evidence set is known before generation starts.** Whether `[E7]` is real
  or invented is decidable the moment it is read, not at the end.

What genuinely does need the end of the text is one invariant: *an answer with
no citations must be a refusal*. Streaming prose and then discovering it cited
nothing would mean withdrawing paragraphs the reader had already read — exactly
what §4 exists to prevent.

So the answer is held until the first marker that resolves. After that the
invariant can no longer fire, because there is at least one citation, and the
remaining ones are guaranteed by construction:

    #1 every [n] has a citation record  - only resolved markers are emitted
    #2 every citation is in the evidence - citations are built from evidence
    #3 no citations means refusal        - held until the first one resolves
    #4 empty text means refusal          - empty text has no marker, so nothing
                                           was ever released

The cost is that the opening sentence appears when its citation does. The prompt
requires a citation after every verifiable statement, so in practice that is one
sentence of delay in exchange for never taking anything back.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ahr.rag.answer import Evidence

# The marker being scanned for, and the longest prefix of one. A delta can end
# mid-marker — `"…量化的是 Kimi K3[E"` — and emitting that would put a stray
# bracket on screen and then have to remove it.
_MARKER = re.compile(r"\[E(\d+)\]")
_PARTIAL_MARKER = re.compile(r"\[E?\d*$")


@dataclass
class AnswerStream:
    """Turns raw model deltas into text that is safe to display immediately.

    Applies exactly the rules `bind_citations` applies to the finished string.
    The two are checked against each other in the tests rather than trusted to
    stay in step, because the failure mode of drift is invisible: the stream
    would show one thing and the stored answer would say another.
    """

    evidence: list[Evidence]
    _known: set[int] = field(init=False)
    _numbering: dict[int, int] = field(default_factory=dict, init=False)
    # Text produced before the first resolved citation. Not sent, and discarded
    # entirely if none ever arrives.
    _held: str = field(default="", init=False)
    _released: bool = field(default=False, init=False)
    # A delta can split a marker, so the tail that might still become one waits.
    _pending: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self._known = {item.number for item in self.evidence}

    @property
    def citation_count(self) -> int:
        return len(self._numbering)

    def feed(self, delta: str) -> str:
        """Consume one raw delta; return the text that is safe to show now."""
        buffer = self._pending + delta
        self._pending = ""

        # Hold back a trailing fragment that could still complete into a marker.
        partial = _PARTIAL_MARKER.search(buffer)
        if partial:
            self._pending = buffer[partial.start() :]
            buffer = buffer[: partial.start()]

        return self._emit(self._rewrite(buffer))

    def finish(self) -> str:
        """Flush whatever is left. A trailing partial marker was never a marker."""
        remainder = self._pending
        self._pending = ""
        return self._emit(self._rewrite(remainder))

    def _rewrite(self, text: str) -> str:
        """Renumber resolved markers, delete invented ones."""

        def replace(match: re.Match[str]) -> str:
            number = int(match.group(1))
            if number not in self._known:
                # Not in the evidence set: the model invented it. Deleted rather
                # than shown, which is the whole point of resolving server-side.
                return ""
            if number not in self._numbering:
                self._numbering[number] = len(self._numbering) + 1
            return f"[{self._numbering[number]}]"

        return _MARKER.sub(replace, text)

    def _emit(self, text: str) -> str:
        if self._released:
            return text

        self._held += text
        if not self._numbering:
            # Still no citation, so this answer could still turn out to be a
            # refusal. Nothing leaves.
            return ""

        self._released = True
        # `bind_citations` strips the finished string; do the same to the front
        # so the streamed text and the stored text start identically.
        released = self._held.lstrip()
        self._held = ""
        return released


# --- pulling `answer_markdown` out of a JSON response as it arrives ----------
#
# The model answers with a JSON object, so the prose is a string value inside
# it. Waiting for the object to close would be waiting for the whole answer,
# which is the thing being fixed.


class JsonStringExtractor:
    """Yields the decoded content of one top-level string field as it streams.

    A deliberately small scanner rather than a streaming JSON parser: only one
    field is needed, the object shape is fixed by the prompt, and anything this
    misreads is caught when the complete response is parsed and validated at the
    end. It never decides anything — it only decides *when* to show something
    that is verified again afterwards.
    """

    def __init__(self, field_name: str) -> None:
        self._needle = f'"{field_name}"'
        self._buffer = ""
        self._inside = False
        self._done = False
        # An escape sequence can be cut anywhere: `\`, or `\u4e` with the rest
        # arriving next time. The incomplete tail is carried rather than
        # interpreted — the first version tracked "am I mid-escape?" as a flag,
        # which was enough for `\n` and silently dropped the `u4e` of a `中`
        # split at the wrong byte.
        self._carry = ""

    def feed(self, delta: str) -> str:
        if self._done:
            return ""

        if not self._inside:
            self._buffer += delta
            start = self._find_value_start(self._buffer)
            if start is None:
                # Keep only enough to recognise the key across a split.
                self._buffer = self._buffer[-len(self._needle) - 8 :]
                return ""
            rest = self._buffer[start:]
            self._buffer = ""
            self._inside = True
            return self._consume(rest)

        return self._consume(delta)

    def _find_value_start(self, text: str) -> int | None:
        """Index just past the opening quote of the field's value, if present."""
        key = text.find(self._needle)
        if key < 0:
            return None
        colon = text.find(":", key + len(self._needle))
        if colon < 0:
            return None
        quote = text.find('"', colon + 1)
        if quote < 0:
            return None
        return quote + 1

    def _consume(self, text: str) -> str:
        text = self._carry + text
        self._carry = ""

        out: list[str] = []
        index = 0
        length = len(text)

        while index < length:
            char = text[index]

            if char == "\\":
                following = text[index + 1] if index + 1 < length else ""
                # Not enough characters to know what this escape is yet.
                if not following or (following == "u" and index + 6 > length):
                    self._carry = text[index:]
                    break
                if following == "u":
                    out.append(_unescape_unicode(text[index + 2 : index + 6]))
                    index += 6
                else:
                    out.append(_SIMPLE_ESCAPES.get(following, following))
                    index += 2
                continue

            if char == '"':
                # An unescaped quote closes the value.
                self._done = True
                return "".join(out)

            out.append(char)
            index += 1

        return "".join(out)


_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


def _unescape_unicode(digits: str) -> str:
    try:
        return str(json.loads(f'"\\u{digits}"'))
    except (json.JSONDecodeError, ValueError):
        return ""

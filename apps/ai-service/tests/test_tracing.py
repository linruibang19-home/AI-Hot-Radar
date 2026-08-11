"""OpenTelemetry spans for the answer pipeline (T4-9).

Per-stage timing already existed in `rag_query.metrics` and on `/ops`; what
tracing adds is one *specific* request as a tree. The properties worth pinning
are about it staying out of the way: absent configuration, absent dependency,
and a collector that has gone away must all cost nothing.
"""

from __future__ import annotations

import inspect

from ahr import tracing
from ahr.rag import service


def test_tracing_is_off_without_an_endpoint(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A diagnostic that changes behaviour when nobody is looking at it is a
    liability — this path is already three provider round trips deep."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert tracing.configure("test") is False


def test_a_blank_endpoint_is_the_same_as_none(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`.env.example` ships the variable with an empty value, so blank has to
    mean off rather than "export to nowhere and block"."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "   ")
    assert tracing.configure("test") is False


def test_the_span_helper_is_a_no_op_when_disabled() -> None:
    with tracing.span("rag.answer", question_chars=12) as current:
        assert current is None
        # And annotating a no-op span is safe, so callers need no guard.
        tracing.annotate(current, evidence=10)


def test_a_missing_exporter_degrades_rather_than_crashes() -> None:
    """The dependency is optional on purpose: a deployment that collects no
    traces should not have to carry an exporter."""
    source = inspect.getsource(tracing.configure)
    assert "except ImportError" in source
    assert "return False" in source


def test_export_is_batched_not_synchronous() -> None:
    """A slow collector must not become a slow answer."""
    assert "BatchSpanProcessor" in inspect.getsource(tracing.configure)


def test_spans_carry_the_request_id_already_required_on_every_log_line() -> None:
    """`AHR-QSO-700` §5 already mandates it across Java and Python, so a trace
    and its logs line up without inventing a second identifier."""
    assert "current_request_id" in inspect.getsource(tracing.span)


def test_stages_are_instrumented_once_rather_than_nine_times() -> None:
    """The stages already announce themselves for the SSE progress stream.
    Hanging the span events off that reporter keeps instrumentation in one
    place; nine separate call sites would drift the first time one moved."""
    source = inspect.getsource(service.retrieve)
    assert "add_stage_event(" in source
    assert source.count("add_stage_event(") == 1


def test_the_stage_event_helper_checks_before_importing() -> None:
    """`opentelemetry` is not installed in the default image, so the import has
    to sit behind the enabled check rather than at module scope."""
    source = inspect.getsource(service.add_stage_event)
    assert source.index("tracing.enabled()") < source.index("from opentelemetry")

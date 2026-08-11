"""OpenTelemetry spans for the answer pipeline (T4-9).

The project already records where the time goes: `rag_query.metrics.stages_ms`
holds a per-stage breakdown for every question ever asked, and `/ops` renders
the distribution. What that cannot do is show one *specific* slow request as a
tree — which stage blocked, what it was waiting on, and how it relates to the
browser request that started it.

**Off unless configured.** With no `OTEL_EXPORTER_OTLP_ENDPOINT` this installs a
no-op tracer, so the pipeline runs unchanged and nothing is exported. Tracing is
a diagnostic, and a diagnostic that changes behaviour when nobody is looking at
it is a liability — the RAG path is already three provider round trips deep
without adding an exporter that can block.

**Reuses `request_id` as the correlation key.** `AHR-QSO-700` §5 already
requires it on every log line across Java and Python, so putting it on the span
means a trace and its logs can be lined up without inventing a second id.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_tracer: Any = None
_enabled = False


def configure(service_name: str) -> bool:
    """Install a tracer if an endpoint is configured. Returns whether it is on."""
    global _tracer, _enabled

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        # The dependency is optional on purpose: a deployment that does not
        # collect traces should not have to carry the exporter.
        logger.info("tracing not installed, continuing without it: %s", exc)
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # Batched, never synchronous: a slow collector must not become a slow answer.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    _tracer = trace.get_tracer(service_name)
    _enabled = True
    logger.info("tracing enabled, exporting to %s", endpoint)
    return True


def enabled() -> bool:
    return _enabled


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """One stage of the pipeline.

    A plain context manager rather than a decorator so the caller can attach
    attributes discovered *during* the stage — how many candidates a channel
    returned is not knowable before it runs, and that count is the thing worth
    seeing on the span.
    """
    if not _enabled or _tracer is None:
        yield None
        return

    from ahr.observability import current_request_id

    with _tracer.start_as_current_span(name) as current:
        current.set_attribute("ahr.request_id", current_request_id())
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(f"ahr.{key}", value)
        yield current


def annotate(current: Any, **attributes: Any) -> None:
    """Attach what the stage learned. Safe to call with a no-op span."""
    if current is None:
        return
    for key, value in attributes.items():
        if value is not None:
            current.set_attribute(f"ahr.{key}", value)

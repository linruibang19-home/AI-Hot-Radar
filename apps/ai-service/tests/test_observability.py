"""Structured logging tests."""

from __future__ import annotations

import json
import logging

from ahr.observability import JsonFormatter


def record(message: str, *, level: int = logging.INFO) -> logging.LogRecord:
    entry = logging.LogRecord("ahr.test", level, __file__, 1, message, None, None)
    entry.request_id = "req-123"
    return entry


def test_output_is_valid_json() -> None:
    """Regression: a stray brace made every line unparseable."""
    line = JsonFormatter("ai-service").format(record("tick claimed=10"))
    assert json.loads(line)["message"] == "tick claimed=10"


def test_quotes_in_message_do_not_break_the_line() -> None:
    """Error text routinely contains quotes; interpolation would corrupt it."""
    line = JsonFormatter("ai-service").format(record('failed: {"error": "boom"}'))
    assert json.loads(line)["message"] == 'failed: {"error": "boom"}'


def test_backslashes_survive() -> None:
    line = JsonFormatter("ai-service").format(record(r"path C:\temp\x"))
    assert json.loads(line)["message"] == r"path C:\temp\x"


def test_request_id_and_service_are_carried() -> None:
    parsed = json.loads(JsonFormatter("worker").format(record("hello")))
    assert parsed["service"] == "worker"
    assert parsed["request_id"] == "req-123"
    assert parsed["logger"] == "ahr.test"


def test_missing_request_id_defaults_rather_than_crashing() -> None:
    entry = logging.LogRecord("ahr.test", logging.INFO, __file__, 1, "no filter", None, None)
    assert json.loads(JsonFormatter("s").format(entry))["request_id"] == "-"


def test_cjk_is_not_escaped() -> None:
    parsed = json.loads(JsonFormatter("s").format(record("模型发布")))
    assert parsed["message"] == "模型发布"

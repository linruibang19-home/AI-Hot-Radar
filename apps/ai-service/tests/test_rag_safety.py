"""Publication safety canaries for untrusted RAG output."""

from __future__ import annotations

import inspect

from ahr.rag import service
from ahr.rag.safety import credential_labels


def test_credential_detector_returns_labels_not_secret_values() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    labels = credential_labels(f"配置值是 {secret}")
    assert labels == ("openai_style_key",)
    assert secret not in labels


def test_private_keys_authorization_headers_and_cloud_keys_are_blocked() -> None:
    text = """-----BEGIN PRIVATE KEY-----
Authorization: Bearer definitely-not-safe
ghp_abcdefghijklmnopqrstuvwxyz12
AKIAABCDEFGHIJKLMNOP
"""
    assert credential_labels(text) == (
        "private_key",
        "authorization_header",
        "github_token",
        "aws_access_key",
    )


def test_security_news_and_short_example_keys_are_not_false_positives() -> None:
    text = "这篇文章讨论 prompt injection、API key 与 sk-test 示例，但没有真实凭据。"
    assert credential_labels(text) == ()


def test_credential_gate_runs_before_persistence_and_clears_all_public_fields() -> None:
    source = inspect.getsource(service.answer_question)
    gate = source.index("credential_kinds = credential_labels")
    result = source.index("result = Answer(", gate)
    persist = source.index("_persist(connection, result)", result)
    assert gate < result < persist
    assert 'limitations = ["候选答案包含疑似访问凭据，已阻止发布。"]' in source
    assert "considered=[] if credential_blocked" in source

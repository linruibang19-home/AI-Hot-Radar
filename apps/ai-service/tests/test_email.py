"""Report email rendering and delivery-key tests (M2)."""

from __future__ import annotations

import pytest

from ahr.processing.email import (
    EmailNotConfiguredError,
    SmtpConfig,
    build_message,
    delivery_key,
    render_html,
)

MARKDOWN = """# AI Hot Radar 日报 · 2026-08-01

今日总述内容。

## 模型发布

- **[DeepSeek V4-Flash 发布](https://example.com/a)** · Latent Space
  该模型在编码基准上大幅提升。

---

本报告由 AI Hot Radar 自动生成。摘要为 AI 生成内容，事实请以原文为准。"""


def config() -> SmtpConfig:
    return SmtpConfig(
        host="smtp.example.com",
        port=587,
        username="user",
        password="secret",
        sender="radar@example.com",
    )


# --- delivery key --------------------------------------------------------


def test_delivery_key_is_stable_for_the_same_pair() -> None:
    assert delivery_key("2026-08-01", "a@example.com") == delivery_key(
        "2026-08-01", "a@example.com"
    )


def test_delivery_key_ignores_recipient_case() -> None:
    """Otherwise the same person could be mailed twice."""
    assert delivery_key("2026-08-01", "A@Example.com") == delivery_key(
        "2026-08-01", "a@example.com"
    )


def test_delivery_key_differs_per_recipient_and_date() -> None:
    base = delivery_key("2026-08-01", "a@example.com")
    assert base != delivery_key("2026-08-01", "b@example.com")
    assert base != delivery_key("2026-08-02", "a@example.com")


def test_delivery_key_does_not_leak_the_address() -> None:
    """The key is stored; the raw address should not be recoverable from it."""
    assert "example.com" not in delivery_key("2026-08-01", "a@example.com")


# --- html rendering ------------------------------------------------------


def test_html_links_to_the_publisher() -> None:
    html = render_html("标题", "总述", MARKDOWN)
    assert 'href="https://example.com/a"' in html


def test_html_uses_inline_styles_only() -> None:
    """Email clients strip <style> blocks, so styling must be inline."""
    html = render_html("标题", "总述", MARKDOWN)
    assert "<style" not in html
    assert 'style="' in html


def test_html_carries_the_ai_disclaimer() -> None:
    html = render_html("标题", "总述", MARKDOWN)
    assert "AI" in html
    assert "原文为准" in html


def test_html_escapes_titles_from_third_party_sources() -> None:
    """Item titles come from external sites and must never be injected raw."""
    hostile = "## 模型发布\n\n- **[<img src=x onerror=alert(1)>](https://e.com/a)** · Src\n"
    html = render_html("标题", "", hostile)
    assert "<img src=x" not in html
    assert "&lt;img" in html


def test_html_keeps_a_malformed_line_as_text() -> None:
    """A broken entry should still be visible rather than silently dropped."""
    html = render_html("标题", "", "- **[unclosed link · Src\n")
    assert "unclosed link" in html


# --- message assembly ----------------------------------------------------


def test_message_has_plain_text_and_html_parts() -> None:
    message = build_message(
        config=config(),
        recipient="reader@example.com",
        title="日报",
        summary="总述",
        body_markdown=MARKDOWN,
    )
    types = {part.get_content_type() for part in message.walk()}
    assert "text/plain" in types
    assert "text/html" in types


def test_message_headers_are_set() -> None:
    message = build_message(
        config=config(),
        recipient="reader@example.com",
        title="日报标题",
        summary="",
        body_markdown=MARKDOWN,
    )
    assert message["To"] == "reader@example.com"
    assert message["Subject"] == "日报标题"
    assert "radar@example.com" in message["From"]


# --- configuration -------------------------------------------------------


def test_missing_smtp_config_raises_a_distinct_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not configured is not the same failure as a send error."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    with pytest.raises(EmailNotConfiguredError):
        SmtpConfig.from_env()


def test_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("EMAIL_FROM", "from@test")
    monkeypatch.setenv("SMTP_PORT", "2525")

    loaded = SmtpConfig.from_env()
    assert loaded.host == "smtp.test"
    assert loaded.port == 2525

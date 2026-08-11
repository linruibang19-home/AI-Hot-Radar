"""Report email delivery.

AHR-FEAT-105 requires web, email and RSS to render the same report facts, so
this reads the stored report rather than regenerating anything.

AHR-ARCH-200 §5 requires a `delivery_key` so a retry cannot send the same
report twice — an email, unlike a page render, is not idempotent from the
recipient's point of view.
"""

from __future__ import annotations

import hashlib
import logging
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

logger = logging.getLogger(__name__)


class EmailNotConfiguredError(RuntimeError):
    """SMTP settings are missing. Distinct from a send failure."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    sender_name: str = "AI Hot Radar"
    use_tls: bool = True
    timeout: float = 20.0

    @classmethod
    def from_env(cls) -> SmtpConfig:
        import os

        host = os.environ.get("SMTP_HOST", "").strip()
        sender = os.environ.get("EMAIL_FROM", "").strip()
        if not host or not sender:
            raise EmailNotConfiguredError("SMTP_HOST and EMAIL_FROM must be set")

        return cls(
            host=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USERNAME", "").strip(),
            password=os.environ.get("SMTP_PASSWORD", "").strip(),
            sender=sender,
            sender_name=os.environ.get("EMAIL_FROM_NAME", "AI Hot Radar").strip(),
        )


def delivery_key(report_date: str, recipient: str) -> str:
    """Stable key for one report to one recipient.

    Hashing the pair means a resend attempt is recognisable even though the
    recipient address itself is never stored in the key.
    """
    return hashlib.sha256(f"daily:{report_date}:{recipient.lower()}".encode()).hexdigest()


def render_html(title: str, summary: str, body_markdown: str) -> str:
    """Minimal HTML rendering of the stored markdown.

    Inline styles only: email clients strip <style> blocks and have no CSS
    variable support, so the site stylesheet cannot be reused here.
    """
    from html import escape

    parts: list[str] = []
    for line in body_markdown.split("\n"):
        if line.startswith("# "):
            continue  # the title is already the email subject and heading
        if line.startswith("## "):
            parts.append(
                f'<h2 style="font-size:15px;margin:22px 0 8px;'
                f'border-bottom:1px solid #e4e4e0;padding-bottom:5px">'
                f"{escape(line[3:])}</h2>"
            )
        elif line.startswith("- **["):
            # "- **[title](url)** · source"
            try:
                title_part = line[line.index("[") + 1 : line.index("](")]
                url_part = line[line.index("](") + 2 : line.index(")**")]
                source_part = line.split("·", 1)[1].strip() if "·" in line else ""
                parts.append(
                    f'<p style="margin:10px 0 2px">'
                    f'<a href="{escape(url_part, quote=True)}" '
                    f'style="color:#0f6e5c;text-decoration:none;font-weight:600">'
                    f"{escape(title_part)}</a>"
                    f'<span style="color:#6b6b66;font-size:12px;margin-left:8px">'
                    f"{escape(source_part)}</span></p>"
                )
            except ValueError:
                # A malformed line is shown as text rather than dropped.
                parts.append(f'<p style="margin:6px 0">{escape(line)}</p>')
        elif line.startswith("  "):
            parts.append(
                f'<p style="margin:0 0 8px;font-size:13px;color:#43433f">{escape(line.strip())}</p>'
            )
        elif line.startswith("---"):
            parts.append('<hr style="border:0;border-top:1px solid #e4e4e0;margin:20px 0">')
        elif line.strip():
            parts.append(f'<p style="margin:0 0 12px">{escape(line)}</p>')

    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><body style="margin:0;padding:24px;background:#f7f7f5;
font-family:system-ui,-apple-system,'Segoe UI','PingFang SC',sans-serif;color:#1a1a18">
<div style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e4e4e0;
border-radius:10px;padding:28px">
<h1 style="font-size:20px;margin:0 0 18px">{escape(title)}</h1>
{body}
<p style="margin-top:24px;font-size:12px;color:#6b6b66">
本邮件由 AI Hot Radar 自动生成。摘要为 AI 生成内容，事实请以原文为准。</p>
</div></body></html>"""


def build_message(
    *, config: SmtpConfig, recipient: str, title: str, summary: str, body_markdown: str
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = formataddr((config.sender_name, config.sender))
    message["To"] = recipient

    # Plain text first, HTML as the alternative: a client that cannot render
    # HTML still gets a readable digest.
    message.set_content(body_markdown)
    message.add_alternative(render_html(title, summary, body_markdown), subtype="html")
    return message


def already_delivered(connection: Any, key: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM email_delivery WHERE delivery_key = %s", (key,))
        return cursor.fetchone() is not None


def record_delivery(
    connection: Any, *, key: str, recipient: str, report_date: str, status: str, error: str | None
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO email_delivery (
                id, delivery_key, recipient, report_period_key, status, error_detail
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (delivery_key) DO UPDATE SET
                status = EXCLUDED.status,
                error_detail = EXCLUDED.error_detail,
                attempted_at = now()
            """,
            (uuid.uuid4(), key, recipient, report_date, status, (error or "")[:500] or None),
        )
    connection.commit()


def report_delivery_allowed(status: str, *, dry_run: bool) -> bool:
    """Preview any stored edition; formally deliver only published reports."""
    return dry_run or status == "PUBLISHED"


def send_message(config: SmtpConfig, message: EmailMessage) -> None:
    """Deliver via SMTP with STARTTLS."""
    context = ssl.create_default_context()
    with smtplib.SMTP(config.host, config.port, timeout=config.timeout) as server:
        if config.use_tls:
            server.starttls(context=context)
        if config.username:
            server.login(config.username, config.password)
        server.send_message(message)

"""Small production health monitor with bounded webhook alerts.

It deliberately has no Docker socket and cannot restart or mutate services.
Readiness, web liveness and backup freshness are enough to tell an operator
that the single-host deployment needs attention without making the monitor a
second orchestrator.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"service":"monitor","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger("production-monitor")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


TARGETS = {
    "core-api": "http://core-api:8080/health/ready",
    "ai-service": "http://ai-service:8000/health/ready",
    "web": "http://web:3000/health",
}

FEISHU_WEBHOOK_HOSTS = {"open.feishu.cn", "open.larksuite.com"}


def check_url(name: str, url: str, *, timeout: float = 5.0) -> Check:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed URLs
            if response.status != 200:
                return Check(name, False, f"http_{response.status}")
            return Check(name, True, "ok")
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return Check(name, False, type(exc).__name__)


def check_backup(
    directory: Path, *, max_age_seconds: int, now: float | None = None
) -> Check:
    dumps = list(directory.glob("ai_hot_radar-*.dump")) if directory.exists() else []
    if not dumps:
        return Check("backup", False, "missing")
    newest = max(dumps, key=lambda path: path.stat().st_mtime)
    age = int((time.time() if now is None else now) - newest.stat().st_mtime)
    if age > max_age_seconds:
        return Check("backup", False, f"stale_{age}s")
    if newest.stat().st_size == 0:
        return Check("backup", False, "empty")
    if not newest.with_suffix(newest.suffix + ".sha256").exists():
        return Check("backup", False, "checksum_missing")
    return Check("backup", True, f"age_{age}s")


def run_checks() -> list[Check]:
    checks = [check_url(name, url) for name, url in TARGETS.items()]
    checks.append(
        check_backup(
            Path(os.environ.get("BACKUP_DIR", "/backups")),
            max_age_seconds=int(os.environ.get("BACKUP_MAX_AGE_SECONDS", "93600")),
        )
    )
    return checks


def webhook_payload(webhook: str, message: str) -> dict[str, object]:
    """Build the provider-specific payload without leaking webhook credentials."""
    hostname = (urllib.parse.urlparse(webhook).hostname or "").lower()
    if hostname in FEISHU_WEBHOOK_HOSTS:
        return {"msg_type": "text", "content": {"text": message}}
    return {"text": message}


def notify(message: str) -> bool:
    webhook = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        logger.error("alert webhook is not configured; event=%s", message)
        return False
    request = urllib.request.Request(
        webhook,
        data=json.dumps(webhook_payload(webhook, message), ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - operator URL
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        logger.error("failed to deliver alert: %s", type(exc).__name__)
        return False


def main() -> int:
    once = "--once" in sys.argv
    threshold = max(int(os.environ.get("ALERT_FAILURE_THRESHOLD", "3")), 1)
    interval = max(int(os.environ.get("MONITOR_INTERVAL_SECONDS", "60")), 10)
    failures = {name: 0 for name in (*TARGETS, "backup")}
    alerted: set[str] = set()

    while True:
        checks = run_checks()
        for check in checks:
            if check.ok:
                if check.name in alerted:
                    notify(f"AI Hot Radar recovered: {check.name}")
                    alerted.remove(check.name)
                failures[check.name] = 0
            else:
                failures[check.name] += 1
                logger.warning(
                    "check failed: name=%s detail=%s consecutive=%s",
                    check.name,
                    check.detail,
                    failures[check.name],
                )
                if failures[check.name] >= threshold and check.name not in alerted:
                    notify(f"AI Hot Radar alert: {check.name} {check.detail}")
                    alerted.add(check.name)

        if once:
            return 0 if all(check.ok for check in checks) else 1
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())

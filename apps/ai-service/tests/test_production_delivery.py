"""Production assets are executable gates, not deployment-shaped prose."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]


def load_monitor():
    path = REPO / "infra" / "scripts" / "monitor.py"
    spec = importlib.util.spec_from_file_location("production_monitor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_preflight_accepts_only_the_explicit_structural_fixture() -> None:
    if shutil.which("sh") is None:
        pytest.skip("POSIX shell validation runs in the Linux CI/container gate")
    result = subprocess.run(
        [
            "sh",
            str(REPO / "infra" / "scripts" / "preflight.sh"),
            str(REPO / "infra" / "compose" / "preflight.env.example"),
        ],
        env={**os.environ, "PREFLIGHT_ALLOW_EXAMPLE": "true"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "preflight OK" in result.stdout


def test_preflight_rejects_a_mutable_image_tag(tmp_path: Path) -> None:
    if shutil.which("sh") is None:
        pytest.skip("POSIX shell validation runs in the Linux CI/container gate")
    source = (REPO / "infra" / "compose" / "preflight.env.example").read_text(encoding="utf-8")
    candidate = tmp_path / "production.env"
    candidate.write_text(
        source.replace("PREFLIGHT_EXAMPLE=true", "PREFLIGHT_EXAMPLE=false").replace(
            "IMAGE_TAG=sha-0000000000000000000000000000000000000000",
            "IMAGE_TAG=latest",
        )
    )
    candidate.chmod(0o600)
    result = subprocess.run(
        ["sh", str(REPO / "infra" / "scripts" / "preflight.sh"), str(candidate)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "immutable" in result.stderr


def test_production_compose_exposes_only_caddy() -> None:
    compose = yaml.safe_load(
        (REPO / "infra" / "compose" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    exposed = {name for name, service in services.items() if service.get("ports")}
    assert exposed == {"caddy"}
    assert all("build" not in service for service in services.values())
    assert services["restore-verify"]["profiles"] == ["tools"]
    assert services["monitor"]["healthcheck"]["disable"] is True
    for service_name in ("ai-service", "scheduler", "pipeline"):
        assert services[service_name]["depends_on"]["redis"]["condition"] == "service_healthy"


def test_release_build_waits_for_the_reusable_full_gate() -> None:
    release = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/ci.yml" in release
    assert "needs: verify" in release
    assert "workflow_call:" in ci


def test_caddy_trusts_cloudflare_strictly_instead_of_private_ranges() -> None:
    caddy = (REPO / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    assert "trusted_proxies_strict" in caddy
    assert "client_ip_headers CF-Connecting-IP" in caddy
    assert "103.21.244.0/22" in caddy
    assert "2c0f:f248::/32" in caddy
    assert "trusted_proxies static private_ranges" not in caddy


def test_backup_check_requires_a_recent_nonempty_dump_and_checksum(tmp_path: Path) -> None:
    monitor = load_monitor()
    missing = monitor.check_backup(tmp_path, max_age_seconds=60, now=1000)
    assert missing.ok is False
    assert missing.detail == "missing"

    dump = tmp_path / "ai_hot_radar-20260811T000000Z.dump"
    dump.write_bytes(b"dump")
    os.utime(dump, (950, 950))
    no_checksum = monitor.check_backup(tmp_path, max_age_seconds=60, now=1000)
    assert no_checksum.detail == "checksum_missing"

    dump.with_suffix(".dump.sha256").write_text("checksum")
    healthy = monitor.check_backup(tmp_path, max_age_seconds=60, now=1000)
    assert healthy.ok is True
    assert healthy.detail == "age_50s"


@pytest.mark.parametrize(
    "webhook",
    [
        "https://open.feishu.cn/open-apis/bot/v2/hook/example",
        "https://open.larksuite.com/open-apis/bot/v2/hook/example",
    ],
)
def test_monitor_builds_feishu_text_payload(webhook: str) -> None:
    monitor = load_monitor()

    assert monitor.webhook_payload(webhook, "AI Hot Radar alert: backup missing") == {
        "msg_type": "text",
        "content": {"text": "AI Hot Radar alert: backup missing"},
    }


def test_monitor_preserves_generic_webhook_payload() -> None:
    monitor = load_monitor()

    assert monitor.webhook_payload(
        "https://hooks.example.test/services/example",
        "AI Hot Radar recovered: web",
    ) == {"text": "AI Hot Radar recovered: web"}


def test_backup_script_catalog_checks_before_publishing_dump() -> None:
    script = (REPO / "infra" / "scripts" / "backup.sh").read_text(encoding="utf-8")
    assert 'pg_restore --list "$target.partial"' in script
    assert 'sha256sum "$target"' in script
    assert "BACKUP_RUN_ONCE" in script

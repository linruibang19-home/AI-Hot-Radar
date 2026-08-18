"""The production compose file, checked without a server (M5).

It had never been parsed. Adding the spend ceiling put a second `environment:`
key on `core-api`, which is a YAML error — the file would not have started at
all, and the first place that would have surfaced is a fresh machine during a
deploy.

These are static checks on purpose: they catch the class of mistake that costs
an hour on a rented box, and they run in CI where there is no Docker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE = Path(__file__).resolve().parents[3] / "infra" / "compose" / "docker-compose.prod.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    # `safe_load` rejects duplicate keys the way Compose does, which is the
    # failure this file exists to catch.
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_it_parses_at_all(compose: dict) -> None:
    assert compose["services"], "no services parsed"


def test_every_service_has_bounded_local_logs(compose: dict) -> None:
    for name, service in compose["services"].items():
        assert service.get("logging") == {
            "driver": "local",
            "options": {"max-size": "10m", "max-file": "3"},
        }, f"{name} can grow unbounded container logs"


def test_only_the_proxy_is_exposed(compose: dict) -> None:
    """Everything else reaches the internet through Caddy. A stray mapping here
    is an unauthenticated service on a public IP — `ai-service` in particular
    answers `/rag/ask`, which spends money."""
    published = {
        (name, port)
        for name, service in compose["services"].items()
        for port in service.get("ports", [])
    }
    assert {name for name, _ in published} <= {"caddy"}, published
    assert {str(p) for _, p in published} <= {"80:80", "443:443"}, published


def test_the_spend_ceiling_is_on_the_service_that_answers(compose: dict) -> None:
    """It guards `/rag/ask`. Set on core-api — where it was first written — it
    would be read by nothing."""
    services = compose["services"]
    assert "LLM_DAILY_TOKEN_LIMIT" in services["ai-service"]["environment"]
    assert "LLM_DAILY_TOKEN_LIMIT" not in services.get("core-api", {}).get("environment", {})


def test_every_secret_is_required_rather_than_defaulted(compose: dict) -> None:
    """A default password is worse than a startup failure: the deployment comes
    up looking healthy and is not."""
    raw = COMPOSE.read_text(encoding="utf-8")
    for secret in (
        "POSTGRES_PASSWORD",
        "INTERNAL_SERVICE_TOKEN",
        "AHR_ADMIN_BOOTSTRAP_TOKEN",
    ):
        assert f"${{{secret}:?" in raw, f"{secret} has a default or is unguarded"


def test_every_generation_worker_can_decrypt_a_stored_credential(compose: dict) -> None:
    """V027 puts the provider key in PostgreSQL behind an AES envelope.

    Three containers build a generation client, and they do not fail the same
    way without the key. `core-api` and `ai-service` would answer that the
    console cannot store one — a save button returning 503, a feature that looks
    present and is not — while `pipeline` would start and then fail every
    enrichment, reason and report, silently, one pass at a time.

    Shipped once without this: the local stack had the variable and production
    did not, so every gate passed and the feature would have been dead on
    arrival.
    """
    services = compose["services"]
    for name in ("core-api", "ai-service", "pipeline"):
        assert "LLM_CREDENTIAL_MASTER_KEY" in services[name]["environment"], (
            f"{name} builds a generation client but has no credential envelope key"
        )


def test_the_env_file_sits_beside_the_compose_file(compose: dict) -> None:
    """Compose interpolates `${VAR}` only from a `.env` next to the compose
    file, never from the repository root — the local stack was bitten by this
    and every service silently fell back to `change-me`."""
    for name, service in compose["services"].items():
        for entry in service.get("env_file", []):
            path = entry["path"] if isinstance(entry, dict) else entry
            assert not str(path).startswith(".."), f"{name} reads {path}"

"""Health endpoint tests.

`/health/live` must stay dependency-free so a database outage never makes the
process look dead. Readiness is covered by integration tests once Compose is up.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ahr.main import create_app


def test_live_returns_ok_without_dependencies() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ai-service"


def test_request_id_is_echoed_when_supplied() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_request_id_is_generated_when_absent() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.headers["X-Request-ID"]

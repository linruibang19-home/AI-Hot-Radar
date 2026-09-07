"""Health endpoints.

`/health/live` answers "is the process up" and must not touch dependencies.
`/health/ready` reports PostgreSQL and Redis reachability; a degraded dependency
returns 503 so Compose and future orchestrators can act on it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, cast

import psycopg
import redis.asyncio as aioredis
from fastapi import APIRouter, Response
from pydantic import BaseModel

from ahr.config import get_settings

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    checks: dict[str, str]


@router.get("/health/live", response_model=HealthStatus)
async def live() -> HealthStatus:
    settings = get_settings()
    return HealthStatus(status="ok", service=settings.service_name, checks={})


@router.get("/health/ready", response_model=HealthStatus)
async def ready(response: Response) -> HealthStatus:
    settings = get_settings()
    checks: dict[str, str] = {}

    try:
        with (
            psycopg.connect(settings.database_url, connect_timeout=3) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
            cur.fetchone()
        checks["postgres"] = "ok"
    except Exception as exc:  # dependency probes must never raise to the caller
        checks["postgres"] = f"error: {type(exc).__name__}"

    # redis-py 5.x exposes this factory without a typed signature while newer
    # releases type it. Narrow the cross-version boundary once, then keep the
    # Redis client operations checked under strict mypy in both environments.
    redis_from_url = cast(Callable[..., aioredis.Redis], aioredis.from_url)
    client = redis_from_url(
        settings.redis_url,
        socket_connect_timeout=3,
    )
    try:
        await client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    finally:
        await client.aclose()

    healthy = all(value == "ok" for value in checks.values())
    if not healthy:
        response.status_code = 503
    return HealthStatus(
        status="ok" if healthy else "degraded",
        service=settings.service_name,
        checks=checks,
    )


class SourceHealth(BaseModel):
    status: Literal["ok", "stalled"]
    stalled: list[dict[str, object]]


@router.get("/health/sources", response_model=SourceHealth)
def source_health(response: Response) -> SourceHealth:
    """Sources that poll successfully and have never produced a document.

    Separate from `/health/ready` on purpose: this must never restart a
    container. A broken feed is an operator's problem, not a reason to cycle a
    healthy process. It returns 503 only so a polling monitor can treat it as a
    failing check without parsing the body.

    Exists because `openai-news` sat at zero items for 37 days while every
    conventional signal stayed green. See `ingestion/health.py::stalled_sources`.
    """
    from datetime import UTC, datetime

    from ahr.ingestion.health import stalled_sources

    settings = get_settings()
    try:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            stalled = stalled_sources(conn, now=datetime.now(UTC))
    except Exception as exc:  # a probe must not raise
        response.status_code = 503
        return SourceHealth(status="stalled", stalled=[{"error": type(exc).__name__}])

    if stalled:
        response.status_code = 503
    return SourceHealth(status="stalled" if stalled else "ok", stalled=stalled)

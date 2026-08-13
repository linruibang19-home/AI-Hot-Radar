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

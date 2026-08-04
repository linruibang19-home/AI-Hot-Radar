"""Runtime configuration bound from environment variables.

Secrets never carry defaults that would work in production; see `.env.example`
at the repository root for the authoritative variable list.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _database_url_from_parts() -> str | None:
    """Build a psycopg conninfo from the discrete POSTGRES_* variables.

    Two separate traps make this preferable to composing the DSN in
    docker-compose.yml, and both were hit in one sitting:

    1. Compose interpolates `${VAR}` from a `.env` *beside the compose file*,
       never from an `env_file:` entry. `env_file:` only injects into the
       container. So a password kept in the repository-root `.env` reached the
       process but not the interpolation, and every service silently fell back
       to the `change-me` default and failed authentication.

    2. A URL gives "#", "@" and "/" syntactic meaning — fragment, host and
       path. A password containing any of them is truncated rather than
       rejected, which looks exactly like a wrong password. Keyword/value
       conninfo has nothing to escape.

    `DATABASE_URL` still wins when set, so existing deployments and tests are
    unaffected.
    """
    host = os.environ.get("POSTGRES_HOST", "postgres").strip()
    port = os.environ.get("POSTGRES_PORT", "5432").strip()
    name = os.environ.get("POSTGRES_DB", "").strip()
    user = os.environ.get("POSTGRES_USER", "").strip()
    password = os.environ.get("POSTGRES_PASSWORD", "").strip()

    if not (name and user and password):
        return None
    return f"host={host} port={port} dbname={name} user={user} password={password}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    service_name: str = "ai-service"

    database_url: str = "postgresql://ai_hot_radar:change-me@postgres:5432/ai_hot_radar"
    redis_url: str = "redis://redis:6379/0"

    # AHR-ARCH-200 §5: every external call is bounded. Values are seconds.
    http_connect_timeout: float = 5.0
    http_read_timeout: float = 20.0

    crawler_user_agent: str = "AIHotRadarBot/1.0 (+https://example.com/bot)"

    otel_exporter_otlp_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if "DATABASE_URL" not in os.environ:
        composed = _database_url_from_parts()
        if composed:
            settings.database_url = composed
    return settings

"""Runtime configuration bound from environment variables.

Secrets never carry defaults that would work in production; see `.env.example`
at the repository root for the authoritative variable list.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    return Settings()

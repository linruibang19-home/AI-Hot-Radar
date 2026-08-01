"""FastAPI application entry point for the AI/ingestion worker.

Scope per AHR-ARCH-200 §3: source adapters, extraction, enrichment, clustering,
embedding, rerank and answer generation. This service must not own user
permissions, favourites or email business facts.
"""

from __future__ import annotations

from fastapi import FastAPI

from ahr.config import get_settings
from ahr.health import router as health_router
from ahr.observability import RequestIdMiddleware, configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.service_name)

    app = FastAPI(
        title="AI Hot Radar AI Service",
        version="0.1.0",
        docs_url="/docs" if settings.app_env == "local" else None,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health_router)
    return app


app = create_app()

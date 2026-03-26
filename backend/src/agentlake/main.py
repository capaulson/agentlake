"""FastAPI application factory and entrypoint."""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentlake import __version__
from agentlake.config import get_settings
from agentlake.core.database import dispose_engine
from agentlake.core.exceptions import register_exception_handlers
from agentlake.core.middleware import RequestIdMiddleware, TimingMiddleware, setup_logging

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns:
        A fully-configured FastAPI instance ready to serve.
    """
    settings = get_settings()

    application = FastAPI(
        title="AgentLake API",
        description="Distributed, agent-friendly data lake REST API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ── Lifecycle Events ─────────────────────────────────────────────────

    @application.on_event("startup")
    async def on_startup() -> None:
        setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
        logger.info(
            "app.startup",
            version=__version__,
            host=settings.API_HOST,
            port=settings.API_PORT,
        )

        # Auto-discover file adapters
        try:
            from agentlake.adapters.registry import AdapterRegistry

            registry = AdapterRegistry()
            registry.auto_discover()
            logger.info("adapters.discovered")
        except Exception:
            logger.warning("adapters.discovery_failed", exc_info=True)

        # Ensure MinIO bucket exists
        try:
            from agentlake.services.storage import StorageService

            storage = StorageService(settings)
            await storage.ensure_bucket()
            logger.info("minio.bucket_ensured", bucket=settings.MINIO_BUCKET)
        except Exception:
            logger.warning("minio.bucket_ensure_failed", exc_info=True)

    @application.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("app.shutdown")
        await dispose_engine()

    # ── Middleware (order matters: outermost first) ───────────────────────

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
    )
    application.add_middleware(RequestIdMiddleware)
    application.add_middleware(TimingMiddleware)

    # ── Exception Handlers ───────────────────────────────────────────────

    register_exception_handlers(application)

    # ── Routers ──────────────────────────────────────────────────────────

    _register_routers(application)

    return application


def _register_routers(application: FastAPI) -> None:
    """Register all API routers on the application."""
    from agentlake.api.admin import router as admin_router
    from agentlake.api.discover import router as discover_router
    from agentlake.api.graph import router as graph_router
    from agentlake.api.health import router as health_router
    from agentlake.api.query import router as query_router
    from agentlake.api.streaming import router as streaming_router
    from agentlake.api.streaming import ws_router
    from agentlake.api.vault import router as vault_router

    application.include_router(health_router)
    application.include_router(vault_router)
    application.include_router(query_router)
    application.include_router(discover_router)
    application.include_router(admin_router)
    application.include_router(graph_router)
    application.include_router(streaming_router)
    application.include_router(ws_router)


# Module-level app instance (used by uvicorn: `uvicorn agentlake.main:app`)
app = create_app()

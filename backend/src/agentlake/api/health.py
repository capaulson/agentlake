"""Health check router — verifies all infrastructure dependencies.

Provides a single endpoint that checks PostgreSQL, Redis, and MinIO
connectivity and reports per-component status.
"""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake import __version__
from agentlake.config import get_settings
from agentlake.core.database import get_db
from agentlake.schemas.common import Meta, ResponseEnvelope

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["health"])


def _request_id() -> str:
    return structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))


@router.get(
    "/health",
    response_model=ResponseEnvelope[dict],
    summary="Health check",
)
async def health_check(
    db: AsyncSession = Depends(get_db),
) -> ResponseEnvelope[dict]:
    """Health check -- verifies PostgreSQL, Redis, and MinIO connectivity.

    Returns a per-component status with latency information.  Overall status
    is ``healthy`` only if all components are reachable.
    """
    components: dict[str, dict] = {}
    overall_healthy = True

    # ── PostgreSQL ────────────────────────────────────────────────────────
    try:
        start = time.monotonic()
        await db.execute(text("SELECT 1"))
        latency_ms = (time.monotonic() - start) * 1000
        components["postgres"] = {
            "status": "healthy",
            "latency_ms": round(latency_ms, 2),
        }
    except Exception as exc:
        overall_healthy = False
        components["postgres"] = {
            "status": "unhealthy",
            "error": str(exc),
        }
        logger.warning("health_check_postgres_failed", error=str(exc))

    # ── Redis ─────────────────────────────────────────────────────────────
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        start = time.monotonic()
        redis_conn = aioredis.from_url(settings.REDIS_URL)
        try:
            await redis_conn.ping()
            latency_ms = (time.monotonic() - start) * 1000
            components["redis"] = {
                "status": "healthy",
                "latency_ms": round(latency_ms, 2),
            }
        finally:
            await redis_conn.close()
    except ImportError:
        components["redis"] = {
            "status": "unknown",
            "error": "redis.asyncio not installed",
        }
    except Exception as exc:
        overall_healthy = False
        components["redis"] = {
            "status": "unhealthy",
            "error": str(exc),
        }
        logger.warning("health_check_redis_failed", error=str(exc))

    # ── MinIO ─────────────────────────────────────────────────────────────
    try:
        from agentlake.services.storage import StorageService

        settings = get_settings()
        storage = StorageService(settings)
        start = time.monotonic()
        # bucket_exists is a lightweight check
        import asyncio

        exists = await asyncio.to_thread(storage.client.bucket_exists, settings.MINIO_BUCKET)
        latency_ms = (time.monotonic() - start) * 1000
        components["minio"] = {
            "status": "healthy",
            "latency_ms": round(latency_ms, 2),
            "bucket_exists": exists,
        }
    except Exception as exc:
        overall_healthy = False
        components["minio"] = {
            "status": "unhealthy",
            "error": str(exc),
        }
        logger.warning("health_check_minio_failed", error=str(exc))

    status = "healthy" if overall_healthy else "degraded"

    return ResponseEnvelope(
        data={
            "status": status,
            "version": __version__,
            "components": components,
        },
        meta=Meta(request_id=_request_id()),
    )

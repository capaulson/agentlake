"""Streaming router — SSE for processing status and search, WebSocket for dashboard.

Provides real-time data delivery via:
- SSE ``/api/v1/stream/processing/{file_id}`` -- processing progress events
- SSE ``/api/v1/stream/search`` -- incremental search results
- WebSocket ``/ws/dashboard`` -- live dashboard stats feed
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from agentlake.config import get_settings
from agentlake.core.auth import require_role
from agentlake.core.database import get_db
from agentlake.models.document import ProcessedDocument
from agentlake.models.file import File
from agentlake.schemas.search import SearchHit
from agentlake.services.llm_client import LLMClient
from agentlake.services.search import SearchService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/stream", tags=["streaming"])
ws_router = APIRouter(tags=["websocket"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_llm_client() -> LLMClient:
    settings = get_settings()
    return LLMClient(
        gateway_url=settings.LLM_GATEWAY_URL,
        service_token=settings.LLM_GATEWAY_SERVICE_TOKEN,
        service_name="api",
    )


# ── SSE: Processing Status ──────────────────────────────────────────────────


@router.get(
    "/processing/{file_id}",
    summary="SSE stream for processing progress",
)
async def stream_processing_status(
    file_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> EventSourceResponse:
    """Server-Sent Events stream for file processing progress.

    Subscribes to the Redis pub/sub channel ``processing:{file_id}`` and
    yields events as they arrive.  Supports ``Last-Event-ID`` for
    reconnection.  Times out after 5 minutes of no activity.
    """
    last_event_id = request.headers.get("Last-Event-ID")

    async def event_generator() -> AsyncGenerator[dict, None]:
        event_id = int(last_event_id) if last_event_id else 0
        timeout_seconds = 300  # 5 minutes
        start_time = time.monotonic()

        # Try to connect to Redis pub/sub
        redis_conn = None
        pubsub = None
        try:
            import redis.asyncio as aioredis

            settings = get_settings()
            redis_conn = aioredis.from_url(settings.REDIS_URL)
            pubsub = redis_conn.pubsub()
            channel = f"processing:{file_id}"
            await pubsub.subscribe(channel)

            logger.info(
                "sse_processing_subscribed",
                file_id=file_id,
                channel=channel,
            )

            # Send initial status by querying the file
            try:
                from agentlake.core.database import _get_session_factory

                async with _get_session_factory()() as session:
                    stmt = select(File).where(File.id == uuid.UUID(file_id))
                    result = await session.execute(stmt)
                    db_file = result.scalar_one_or_none()
                    if db_file:
                        event_id += 1
                        yield {
                            "event": "status",
                            "id": str(event_id),
                            "data": json.dumps({
                                "file_id": file_id,
                                "status": db_file.status,
                                "filename": db_file.original_filename,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }),
                        }

                        # If already terminal, send complete and stop
                        if db_file.status in ("processed", "failed", "deleting"):
                            event_id += 1
                            yield {
                                "event": "complete",
                                "id": str(event_id),
                                "data": json.dumps({
                                    "file_id": file_id,
                                    "status": db_file.status,
                                    "error": db_file.error_message,
                                }),
                            }
                            return
            except Exception:
                logger.warning("sse_initial_status_failed", file_id=file_id, exc_info=True)

            # Listen for pub/sub messages
            while (time.monotonic() - start_time) < timeout_seconds:
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield {"event": "keepalive", "data": ""}
                    continue

                if message is None:
                    yield {"event": "keepalive", "data": ""}
                    continue

                if message["type"] == "message":
                    event_id += 1
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")

                    try:
                        parsed = json.loads(data)
                        event_type = parsed.get("event", "progress")
                    except (json.JSONDecodeError, AttributeError):
                        event_type = "progress"
                        parsed = {"message": data}

                    yield {
                        "event": event_type,
                        "id": str(event_id),
                        "data": json.dumps(parsed) if isinstance(parsed, dict) else data,
                    }

                    # Stop on terminal events
                    if event_type in ("complete", "error", "failed"):
                        return

            # Timeout reached
            event_id += 1
            yield {
                "event": "timeout",
                "id": str(event_id),
                "data": json.dumps({"message": "Stream timed out after 5 minutes"}),
            }

        except ImportError:
            logger.warning("redis_not_available_for_sse")
            # Fallback: poll the database
            await _poll_file_status(file_id, request, event_id, timeout_seconds=60)
        except Exception:
            logger.error("sse_processing_error", file_id=file_id, exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"message": "Internal server error"}),
            }
        finally:
            if pubsub is not None:
                await pubsub.unsubscribe()
                await pubsub.close()
            if redis_conn is not None:
                await redis_conn.close()

    return EventSourceResponse(event_generator())


async def _poll_file_status(
    file_id: str,
    request: Request,
    start_event_id: int,
    timeout_seconds: int = 60,
) -> AsyncGenerator[dict, None]:
    """Fallback: poll DB for file status when Redis is unavailable."""
    from agentlake.core.database import _get_session_factory

    event_id = start_event_id
    start_time = time.monotonic()
    last_status = ""

    while (time.monotonic() - start_time) < timeout_seconds:
        if await request.is_disconnected():
            break

        try:
            async with _get_session_factory()() as session:
                stmt = select(File).where(File.id == uuid.UUID(file_id))
                result = await session.execute(stmt)
                db_file = result.scalar_one_or_none()

                if db_file and db_file.status != last_status:
                    last_status = db_file.status
                    event_id += 1
                    yield {
                        "event": "status",
                        "id": str(event_id),
                        "data": json.dumps({
                            "file_id": file_id,
                            "status": db_file.status,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }),
                    }

                    if db_file.status in ("processed", "failed", "deleting"):
                        event_id += 1
                        yield {
                            "event": "complete",
                            "id": str(event_id),
                            "data": json.dumps({
                                "file_id": file_id,
                                "status": db_file.status,
                            }),
                        }
                        return
        except Exception:
            logger.warning("poll_file_status_error", file_id=file_id, exc_info=True)

        await asyncio.sleep(2)


# ── SSE: Streaming Search ───────────────────────────────────────────────────


@router.get(
    "/search",
    summary="SSE stream for incremental search results",
)
async def stream_search(
    q: str = Query(..., description="Search query"),
    search_type: str = Query("hybrid", pattern="^(keyword|semantic|hybrid)$"),
    category: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    keyword_weight: float = Query(0.4, ge=0.0, le=1.0),
    semantic_weight: float = Query(0.6, ge=0.0, le=1.0),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> EventSourceResponse:
    """SSE stream that delivers search results incrementally.

    For hybrid search, keyword results are sent first (faster), followed
    by semantic results merged via RRF.
    """
    async def event_generator() -> AsyncGenerator[dict, None]:
        llm_client = _make_llm_client()
        search_service = SearchService(db=db, llm_client=llm_client)

        filters: dict | None = None
        if category:
            filters = {"category": category}

        event_id = 0
        start_time = time.monotonic()

        # Send query acknowledgment
        event_id += 1
        yield {
            "event": "query_accepted",
            "id": str(event_id),
            "data": json.dumps({"query": q, "mode": search_type}),
        }

        if search_type == "hybrid":
            # Send keyword results first (faster)
            try:
                keyword_results = await search_service.keyword_search(
                    query=q, limit=limit, filters=filters
                )
                for hit in keyword_results:
                    event_id += 1
                    yield {
                        "event": "result",
                        "id": str(event_id),
                        "data": json.dumps({
                            **hit,
                            "id": str(hit["id"]),
                            "source_file_id": str(hit["source_file_id"]) if hit.get("source_file_id") else None,
                            "created_at": hit["created_at"].isoformat() if hit.get("created_at") else None,
                            "source": "keyword",
                        }),
                    }

                event_id += 1
                yield {
                    "event": "phase_complete",
                    "id": str(event_id),
                    "data": json.dumps({
                        "phase": "keyword",
                        "count": len(keyword_results),
                    }),
                }
            except Exception:
                logger.warning("stream_keyword_search_failed", exc_info=True)

            # Then send semantic results
            try:
                semantic_results = await search_service.semantic_search(
                    query=q, limit=limit, filters=filters
                )
                for hit in semantic_results:
                    event_id += 1
                    yield {
                        "event": "result",
                        "id": str(event_id),
                        "data": json.dumps({
                            **hit,
                            "id": str(hit["id"]),
                            "source_file_id": str(hit["source_file_id"]) if hit.get("source_file_id") else None,
                            "created_at": hit["created_at"].isoformat() if hit.get("created_at") else None,
                            "source": "semantic",
                        }),
                    }

                event_id += 1
                yield {
                    "event": "phase_complete",
                    "id": str(event_id),
                    "data": json.dumps({
                        "phase": "semantic",
                        "count": len(semantic_results),
                    }),
                }
            except Exception:
                logger.warning("stream_semantic_search_failed", exc_info=True)

        else:
            # Single-mode search
            if search_type == "keyword":
                results = await search_service.keyword_search(
                    query=q, limit=limit, filters=filters
                )
            else:
                results = await search_service.semantic_search(
                    query=q, limit=limit, filters=filters
                )

            for hit in results:
                event_id += 1
                yield {
                    "event": "result",
                    "id": str(event_id),
                    "data": json.dumps({
                        **hit,
                        "id": str(hit["id"]),
                        "source_file_id": str(hit["source_file_id"]) if hit.get("source_file_id") else None,
                        "created_at": hit["created_at"].isoformat() if hit.get("created_at") else None,
                        "source": search_type,
                    }),
                }

        # Final summary event
        elapsed = (time.monotonic() - start_time) * 1000
        event_id += 1
        yield {
            "event": "complete",
            "id": str(event_id),
            "data": json.dumps({
                "query": q,
                "mode": search_type,
                "search_time_ms": round(elapsed, 2),
            }),
        }

    return EventSourceResponse(event_generator())


# ── WebSocket: Dashboard Live Feed ──────────────────────────────────────────


@ws_router.websocket("/ws/dashboard")
async def dashboard_feed(websocket: WebSocket) -> None:
    """WebSocket feed for live dashboard statistics.

    Authenticates via the ``token`` query parameter (API key), then pushes
    aggregated stats every 5 seconds.  Handles disconnects gracefully.
    """
    # Authenticate via query parameter
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token query parameter")
        return

    # Validate the token
    try:
        from agentlake.core.auth import get_current_api_key, hash_api_key
        from agentlake.core.database import _get_session_factory
        from agentlake.models.api_key import ApiKey

        settings = get_settings()
        hashed = hash_api_key(token, settings.API_KEY_SALT)

        async with _get_session_factory()() as session:
            stmt = select(ApiKey).where(
                ApiKey.key_hash == hashed,
                ApiKey.is_active.is_(True),
            )
            result = await session.execute(stmt)
            api_key = result.scalar_one_or_none()

            if api_key is None:
                await websocket.close(code=4003, reason="Invalid API key")
                return
    except Exception:
        logger.warning("ws_auth_failed", exc_info=True)
        await websocket.close(code=4003, reason="Authentication failed")
        return

    await websocket.accept()
    logger.info("ws_dashboard_connected", api_key_id=str(api_key.id))

    try:
        while True:
            # Gather stats
            stats = await _gather_dashboard_stats()

            await websocket.send_json({
                "event": "stats_update",
                "data": stats,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            await asyncio.sleep(5)

    except WebSocketDisconnect:
        logger.info("ws_dashboard_disconnected")
    except Exception:
        logger.error("ws_dashboard_error", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass


async def _gather_dashboard_stats() -> dict:
    """Collect current stats for the dashboard WebSocket feed."""
    from agentlake.core.database import _get_session_factory

    stats: dict = {
        "files": {"total": 0, "by_status": {}},
        "documents": {"total": 0, "by_category": {}},
        "processing": {"active": 0, "pending": 0},
    }

    try:
        async with _get_session_factory()() as session:
            # File counts by status
            file_stmt = (
                select(File.status, func.count().label("count"))
                .where(File.deleted_at.is_(None))
                .group_by(File.status)
            )
            file_result = await session.execute(file_stmt)
            for row in file_result:
                stats["files"]["by_status"][row.status] = row.count
                stats["files"]["total"] += row.count

            stats["processing"]["active"] = stats["files"]["by_status"].get("processing", 0)
            stats["processing"]["pending"] = stats["files"]["by_status"].get("pending", 0)

            # Document counts by category
            doc_stmt = (
                select(
                    ProcessedDocument.category,
                    func.count().label("count"),
                )
                .where(ProcessedDocument.is_current.is_(True))
                .group_by(ProcessedDocument.category)
            )
            doc_result = await session.execute(doc_stmt)
            for row in doc_result:
                stats["documents"]["by_category"][row.category] = row.count
                stats["documents"]["total"] += row.count

            await session.commit()

    except Exception:
        logger.warning("dashboard_stats_query_failed", exc_info=True)

    # Try to get Redis-cached queue info
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        redis_conn = aioredis.from_url(settings.REDIS_URL)
        try:
            queue_len = await redis_conn.llen("default")
            stats["processing"]["queue_length"] = queue_len
        finally:
            await redis_conn.close()
    except Exception:
        stats["processing"]["queue_length"] = None

    return stats

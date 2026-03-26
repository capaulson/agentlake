"""Admin router — API key management, LLM usage, and queue status.

All endpoints require the ``admin`` role.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.config import get_settings
from agentlake.core.auth import hash_api_key, require_role
from agentlake.core.database import get_db
from agentlake.core.exceptions import NotFoundError
from agentlake.models.api_key import ApiKey
from agentlake.models.llm_request import LLMRequest
from agentlake.schemas.common import Meta, ResponseEnvelope

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _request_id() -> str:
    return structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))


# ── List API Keys ────────────────────────────────────────────────────────────


@router.get(
    "/api-keys",
    response_model=ResponseEnvelope[list[dict]],
    summary="List all API keys",
)
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[list[dict]]:
    """Return all API keys (without the raw key or hash)."""
    stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
    result = await db.execute(stmt)
    keys = result.scalars().all()

    key_list = [
        {
            "id": str(k.id),
            "name": k.name,
            "role": k.role,
            "is_active": k.is_active,
            "description": k.description,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "updated_at": k.updated_at.isoformat() if k.updated_at else None,
        }
        for k in keys
    ]

    return ResponseEnvelope(
        data=key_list,
        meta=Meta(request_id=_request_id()),
    )


# ── Create API Key ───────────────────────────────────────────────────────────


@router.post(
    "/api-keys",
    response_model=ResponseEnvelope[dict],
    status_code=201,
    summary="Create a new API key",
)
async def create_api_key(
    name: str = Query(..., min_length=1, max_length=255),
    role: str = Query("viewer", pattern="^(admin|editor|viewer|agent)$"),
    description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Generate a new API key.

    Returns the raw key **once** in the response.  It is hashed before storage
    and cannot be recovered.
    """
    settings = get_settings()

    # Generate a secure random key with prefix for readability
    raw_key = f"al_{secrets.token_urlsafe(32)}"
    key_hash = hash_api_key(raw_key, settings.API_KEY_SALT)

    new_key = ApiKey(
        name=name,
        key_hash=key_hash,
        role=role,
        is_active=True,
        description=description,
    )
    db.add(new_key)
    await db.flush()

    logger.info(
        "api_key_created",
        key_id=str(new_key.id),
        name=name,
        role=role,
    )

    return ResponseEnvelope(
        data={
            "id": str(new_key.id),
            "name": new_key.name,
            "role": new_key.role,
            "key": raw_key,  # Only returned once
            "description": new_key.description,
            "created_at": new_key.created_at.isoformat() if new_key.created_at else None,
            "warning": "Store this key securely. It cannot be retrieved again.",
        },
        meta=Meta(request_id=_request_id()),
    )


# ── Delete API Key ───────────────────────────────────────────────────────────


@router.delete(
    "/api-keys/{key_id}",
    response_model=ResponseEnvelope[dict],
    summary="Deactivate an API key",
)
async def delete_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Deactivate (soft-delete) an API key.

    The key remains in the database for audit purposes but can no longer
    authenticate requests.
    """
    stmt = select(ApiKey).where(ApiKey.id == key_id)
    result = await db.execute(stmt)
    target = result.scalar_one_or_none()
    if target is None:
        raise NotFoundError(f"API key {key_id} not found")

    target.is_active = False
    await db.flush()

    logger.info("api_key_deactivated", key_id=str(key_id), name=target.name)

    return ResponseEnvelope(
        data={"id": str(key_id), "status": "deactivated"},
        meta=Meta(request_id=_request_id()),
    )


# ── LLM Usage ────────────────────────────────────────────────────────────────


@router.get(
    "/llm-usage",
    response_model=ResponseEnvelope[dict],
    summary="LLM usage statistics",
)
async def get_llm_usage(
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    group_by: str = Query(
        "provider",
        pattern="^(provider|model|purpose|caller_service)$",
        description="Group results by this field",
    ),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Get LLM usage statistics from the request ledger.

    Aggregates token counts, estimated costs, and request counts grouped
    by provider, model, purpose, or caller service.
    """
    from datetime import timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    group_column = getattr(LLMRequest, group_by)

    stmt = (
        select(
            group_column.label("group_key"),
            func.count().label("request_count"),
            func.sum(LLMRequest.input_tokens).label("total_input_tokens"),
            func.sum(LLMRequest.output_tokens).label("total_output_tokens"),
            func.sum(LLMRequest.total_tokens).label("total_tokens"),
            func.sum(LLMRequest.estimated_cost_usd).label("total_cost_usd"),
            func.avg(LLMRequest.latency_ms).label("avg_latency_ms"),
        )
        .where(LLMRequest.created_at >= cutoff)
        .group_by(group_column)
        .order_by(func.sum(LLMRequest.total_tokens).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Totals
    totals_stmt = (
        select(
            func.count().label("total_requests"),
            func.sum(LLMRequest.total_tokens).label("total_tokens"),
            func.sum(LLMRequest.estimated_cost_usd).label("total_cost_usd"),
        )
        .where(LLMRequest.created_at >= cutoff)
    )
    totals_result = await db.execute(totals_stmt)
    totals_row = totals_result.one()

    breakdown = [
        {
            "group": row.group_key,
            "request_count": row.request_count,
            "total_input_tokens": row.total_input_tokens or 0,
            "total_output_tokens": row.total_output_tokens or 0,
            "total_tokens": row.total_tokens or 0,
            "total_cost_usd": float(row.total_cost_usd) if row.total_cost_usd else 0.0,
            "avg_latency_ms": round(float(row.avg_latency_ms), 2) if row.avg_latency_ms else 0.0,
        }
        for row in rows
    ]

    return ResponseEnvelope(
        data={
            "period_days": days,
            "grouped_by": group_by,
            "totals": {
                "total_requests": totals_row.total_requests or 0,
                "total_tokens": totals_row.total_tokens or 0,
                "total_cost_usd": float(totals_row.total_cost_usd)
                if totals_row.total_cost_usd
                else 0.0,
            },
            "breakdown": breakdown,
        },
        meta=Meta(request_id=_request_id()),
    )


# ── Queue Status ─────────────────────────────────────────────────────────────


@router.get(
    "/queue-status",
    response_model=ResponseEnvelope[dict],
    summary="Celery queue status",
)
async def get_queue_status(
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Query Celery for active, scheduled, and reserved task counts.

    Returns a best-effort snapshot of the task queues.  If the broker is
    unreachable, returns an error status instead of failing the request.
    """
    try:
        from agentlake.workers.celery_app import celery_app

        inspect = celery_app.control.inspect()

        active = inspect.active() or {}
        scheduled = inspect.scheduled() or {}
        reserved = inspect.reserved() or {}

        # Count tasks per worker
        active_count = sum(len(tasks) for tasks in active.values())
        scheduled_count = sum(len(tasks) for tasks in scheduled.values())
        reserved_count = sum(len(tasks) for tasks in reserved.values())

        workers = list(active.keys() | scheduled.keys() | reserved.keys())

        return ResponseEnvelope(
            data={
                "status": "connected",
                "workers": workers,
                "worker_count": len(workers),
                "active_tasks": active_count,
                "scheduled_tasks": scheduled_count,
                "reserved_tasks": reserved_count,
                "active_by_worker": {
                    worker: len(tasks) for worker, tasks in active.items()
                },
            },
            meta=Meta(request_id=_request_id()),
        )
    except Exception as exc:
        logger.warning("celery_inspect_failed", error=str(exc))

        return ResponseEnvelope(
            data={
                "status": "unavailable",
                "error": str(exc),
                "workers": [],
                "worker_count": 0,
                "active_tasks": 0,
                "scheduled_tasks": 0,
                "reserved_tasks": 0,
            },
            meta=Meta(request_id=_request_id()),
        )


# ── Cross-Document Analysis ──────────────────────────────────────────────


@router.post(
    "/analyze",
    response_model=ResponseEnvelope[dict],
    summary="Trigger cross-document analysis",
)
async def trigger_analysis(
    scope: str = Query("all", description="Scope: all, recent, category:{name}"),
    max_documents: int = Query(50, le=200),
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Run the LangGraph cross-document analysis pipeline.

    Discovers relationships, thematic clusters, contradictions, and
    insights across the document corpus. Results are stored as a
    new analysis document and relationships are added to the entity graph.
    """
    try:
        from agentlake.workers.celery_app import celery_app

        result = celery_app.send_task(
            "analyze_corpus",
            kwargs={"scope": scope, "max_documents": max_documents},
            queue="low",
        )
        task_id = result.id
    except Exception:
        logger.warning("analyze_enqueue_failed", exc_info=True)
        task_id = None

    return ResponseEnvelope(
        data={
            "status": "queued",
            "task_id": task_id,
            "scope": scope,
            "max_documents": max_documents,
        },
        meta=Meta(request_id=_request_id()),
    )


@router.post(
    "/explore",
    response_model=ResponseEnvelope[dict],
    summary="Trigger auto-exploration of follow-up questions",
)
async def trigger_explore(
    max_questions: int = Query(5, le=20),
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Manually trigger the auto-explore agent to investigate follow-up questions."""
    try:
        from agentlake.workers.celery_app import celery_app

        result = celery_app.send_task(
            "auto_explore",
            kwargs={"max_questions": max_questions},
            queue="low",
        )
        task_id = result.id
    except Exception:
        logger.warning("explore_enqueue_failed", exc_info=True)
        task_id = None

    return ResponseEnvelope(
        data={"status": "queued", "task_id": task_id, "max_questions": max_questions},
        meta=Meta(request_id=_request_id()),
    )


# ── System Settings ──────────────────────────────────────────────────────


@router.get(
    "/settings",
    response_model=ResponseEnvelope[dict],
    summary="Get system settings for knowledge discovery",
)
async def get_settings_endpoint(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Get admin-configurable settings for auto-exploration and analysis."""
    from sqlalchemy import text

    result = await db.execute(text("SELECT key, value, description FROM system_settings ORDER BY key"))
    settings_dict = {row[0]: {"value": row[1], "description": row[2]} for row in result.fetchall()}

    # Get current hourly token usage
    usage_result = await db.execute(text("""
        SELECT COALESCE(SUM(tokens_used), 0) FROM knowledge_memory
        WHERE created_at > now() - interval '1 hour'
    """))
    hourly_tokens = usage_result.scalar() or 0

    daily_result = await db.execute(text("""
        SELECT COALESCE(SUM(tokens_used), 0) FROM knowledge_memory
        WHERE created_at > now() - interval '24 hours'
    """))
    daily_tokens = daily_result.scalar() or 0

    return ResponseEnvelope(
        data={
            "settings": settings_dict,
            "usage": {
                "tokens_last_hour": hourly_tokens,
                "tokens_last_24h": daily_tokens,
            },
        },
        meta=Meta(request_id=_request_id()),
    )


@router.put(
    "/settings/{key}",
    response_model=ResponseEnvelope[dict],
    summary="Update a system setting",
)
async def update_setting(
    key: str,
    value: str = Query(...),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Update an admin-configurable setting."""
    from sqlalchemy import text

    valid_keys = [
        "auto_explore_max_tokens_per_hour",
        "auto_explore_max_questions_per_run",
        "auto_explore_enabled",
    ]
    if key not in valid_keys:
        from agentlake.core.exceptions import ValidationError
        raise ValidationError(f"Invalid setting key: {key}. Valid keys: {valid_keys}")

    await db.execute(text("""
        UPDATE system_settings SET value = :val, updated_at = now() WHERE key = :key
    """), {"key": key, "val": value})
    await db.commit()

    return ResponseEnvelope(
        data={"key": key, "value": value, "updated": True},
        meta=Meta(request_id=_request_id()),
    )

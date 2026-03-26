"""Token ledger — records every LLM request for cost tracking and auditing."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.models.llm_request import LLMRequest

logger = structlog.get_logger(__name__)


class TokenLedger:
    """Async service that logs LLM usage and provides aggregated cost reports.

    Every completion or embedding request that passes through the gateway is
    recorded in the ``llm_requests`` table for auditing, cost tracking, and
    usage analytics.
    """

    async def log_request(
        self,
        db: AsyncSession,
        *,
        caller_service: str,
        purpose: str | None,
        model: str,
        provider: str,
        request_type: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        estimated_cost_usd: float | None,
        latency_ms: int,
        status: str,
        error_message: str | None = None,
        fallback_from: str | None = None,
    ) -> LLMRequest:
        """Insert a new ledger entry.

        Args:
            db: Active database session.
            caller_service: Name of the service that initiated the request.
            purpose: Task purpose (maps to task routing, e.g. ``summarize``).
            model: Model identifier used.
            provider: Provider name that served the request.
            request_type: ``"completion"`` or ``"embedding"``.
            input_tokens: Input/prompt tokens consumed.
            output_tokens: Output/completion tokens generated.
            total_tokens: Total tokens.
            estimated_cost_usd: Estimated cost in USD (may be ``None``).
            latency_ms: Wall-clock latency in milliseconds.
            status: ``"success"``, ``"error"``, or ``"fallback"``.
            error_message: Error detail if status is ``"error"``.
            fallback_from: Original provider if a fallback was triggered.

        Returns:
            The persisted :class:`LLMRequest` instance.
        """
        entry = LLMRequest(
            caller_service=caller_service,
            purpose=purpose,
            model=model,
            provider=provider,
            request_type=request_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            fallback_from=fallback_from,
        )
        db.add(entry)
        await db.flush()
        logger.debug(
            "ledger_entry_recorded",
            id=str(entry.id),
            provider=provider,
            model=model,
            tokens=total_tokens,
            cost=estimated_cost_usd,
        )
        return entry

    # ── Aggregation queries ───────────────────────────────────────────────

    async def get_usage(
        self,
        db: AsyncSession,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        group_by: str = "provider",
    ) -> list[dict[str, Any]]:
        """Return aggregated usage statistics.

        Args:
            db: Active database session.
            start_date: Filter — only include requests on or after this time.
            end_date: Filter — only include requests before this time.
            group_by: Column to group by.  Supported: ``provider``, ``model``,
                ``caller_service``, ``purpose``.

        Returns:
            List of dicts with the group key plus aggregated columns.
        """
        valid_groups = {"provider", "model", "caller_service", "purpose"}
        if group_by not in valid_groups:
            group_by = "provider"

        group_col = getattr(LLMRequest, group_by)

        stmt = (
            select(
                group_col.label("group_key"),
                func.count().label("request_count"),
                func.sum(LLMRequest.input_tokens).label("total_input_tokens"),
                func.sum(LLMRequest.output_tokens).label("total_output_tokens"),
                func.sum(LLMRequest.total_tokens).label("total_tokens"),
                func.sum(LLMRequest.estimated_cost_usd).label("total_cost_usd"),
                func.avg(LLMRequest.latency_ms).label("avg_latency_ms"),
            )
            .where(LLMRequest.status != "error")
            .group_by(group_col)
            .order_by(func.sum(LLMRequest.total_tokens).desc())
        )

        if start_date:
            stmt = stmt.where(LLMRequest.created_at >= start_date)
        if end_date:
            stmt = stmt.where(LLMRequest.created_at < end_date)

        result = await db.execute(stmt)
        rows = result.all()
        return [
            {
                group_by: row.group_key,
                "request_count": row.request_count,
                "total_input_tokens": int(row.total_input_tokens or 0),
                "total_output_tokens": int(row.total_output_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
                "total_cost_usd": float(row.total_cost_usd or 0),
                "avg_latency_ms": round(float(row.avg_latency_ms or 0), 1),
            }
            for row in rows
        ]

    async def get_usage_by_service(
        self,
        db: AsyncSession,
        *,
        service: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Return aggregated usage for a specific calling service.

        Args:
            db: Database session.
            service: The ``caller_service`` to filter on.
            start_date: Optional lower bound.
            end_date: Optional upper bound.

        Returns:
            Dict with token totals, cost, and request count.
        """
        stmt = (
            select(
                func.count().label("request_count"),
                func.sum(LLMRequest.input_tokens).label("total_input_tokens"),
                func.sum(LLMRequest.output_tokens).label("total_output_tokens"),
                func.sum(LLMRequest.total_tokens).label("total_tokens"),
                func.sum(LLMRequest.estimated_cost_usd).label("total_cost_usd"),
                func.avg(LLMRequest.latency_ms).label("avg_latency_ms"),
            )
            .where(LLMRequest.caller_service == service)
        )

        if start_date:
            stmt = stmt.where(LLMRequest.created_at >= start_date)
        if end_date:
            stmt = stmt.where(LLMRequest.created_at < end_date)

        result = await db.execute(stmt)
        row = result.one()
        return {
            "caller_service": service,
            "request_count": row.request_count or 0,
            "total_input_tokens": int(row.total_input_tokens or 0),
            "total_output_tokens": int(row.total_output_tokens or 0),
            "total_tokens": int(row.total_tokens or 0),
            "total_cost_usd": float(row.total_cost_usd or 0),
            "avg_latency_ms": round(float(row.avg_latency_ms or 0), 1),
        }

    async def get_daily_cost(
        self,
        db: AsyncSession,
        *,
        day: date | None = None,
    ) -> float:
        """Return total estimated cost for a given day.

        Args:
            db: Database session.
            day: The date to query.  Defaults to today (UTC).

        Returns:
            Total estimated cost in USD.
        """
        if day is None:
            day = date.today()

        stmt = select(
            func.coalesce(func.sum(LLMRequest.estimated_cost_usd), 0.0)
        ).where(
            func.date(LLMRequest.created_at) == day,
        )

        result = await db.execute(stmt)
        return float(result.scalar_one())

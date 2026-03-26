"""SQLAlchemy model for the LLM request ledger."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentlake.models.base import Base, UUIDPrimaryKeyMixin


class LLMRequest(Base, UUIDPrimaryKeyMixin):
    """Ledger entry recording every LLM request routed through the gateway.

    Used for cost tracking, usage analytics, auditing, and rate-limit tuning.
    """

    __tablename__ = "llm_requests"

    caller_service: Mapped[str] = mapped_column(
        String(100), nullable=False, doc="Service that initiated the request."
    )
    purpose: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="Task purpose / routing key."
    )
    model: Mapped[str] = mapped_column(
        String(100), nullable=False, doc="Model identifier used."
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, doc="Provider that served the request."
    )
    request_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="'completion' or 'embedding'.",
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, doc="Input / prompt tokens."
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, doc="Output / completion tokens."
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, doc="Total tokens consumed."
    )
    estimated_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 6), nullable=True, doc="Estimated cost in USD."
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, doc="Wall-clock latency in ms."
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="success",
        doc="'success', 'error', or 'fallback'.",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Error details if status is 'error'."
    )
    fallback_from: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Original provider if a fallback was triggered.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_llm_requests_caller_service", "caller_service"),
        Index("ix_llm_requests_purpose", "purpose"),
        Index("ix_llm_requests_provider", "provider"),
        Index("ix_llm_requests_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<LLMRequest(id={self.id}, provider={self.provider!r}, "
            f"model={self.model!r}, tokens={self.total_tokens})>"
        )

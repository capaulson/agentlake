"""Knowledge Memory model — institutional memory that grows from questions."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentlake.models.base import Base


class KnowledgeMemory(Base):
    """A question asked of the data lake and what was learned.

    Every question becomes institutional memory. Questions cluster into
    themes, generate follow-up questions, and periodically trigger
    deeper analysis — growing the organization's knowledge over time.
    """

    __tablename__ = "knowledge_memory"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    sources_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    question_embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    # Classification
    theme: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities_mentioned: Mapped[dict] = mapped_column(JSONB, server_default="[]")

    # What the system learned
    discoveries: Mapped[dict] = mapped_column(JSONB, server_default="[]")
    follow_up_questions: Mapped[dict] = mapped_column(JSONB, server_default="[]")
    related_question_ids: Mapped[dict] = mapped_column(JSONB, server_default="[]")

    # Feedback loop
    led_to_analysis: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processed_documents.id", ondelete="SET NULL"), nullable=True
    )

    # Meta
    asked_by: Mapped[str] = mapped_column(Text, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

"""Diff log model — records every mutation to processed documents."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentlake.models.base import Base, UUIDPrimaryKeyMixin


class DiffType(str, enum.Enum):
    """Classification of a diff log entry."""

    INITIAL_PROCESSING = "initial_processing"
    REPROCESSING = "reprocessing"
    HUMAN_EDIT = "human_edit"
    AGENT_EDIT = "agent_edit"


class DiffLog(UUIDPrimaryKeyMixin, Base):
    """Immutable audit trail for every change to processed content.

    Critical invariant: every edit (human or automated) produces a
    DiffLog entry recording before_text, after_text, justification,
    and who made the change.  There are no silent mutations.
    """

    __tablename__ = "diff_logs"

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processed_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    diff_type: Mapped[str] = mapped_column(
        VARCHAR(30),
        nullable=False,
        comment="One of: initial_processing, reprocessing, human_edit, agent_edit.",
    )
    before_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Content before the change (null for initial processing).",
    )
    after_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Content after the change.",
    )
    justification: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Reason for the change.",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Additional structured data about the diff (e.g. chunk delta stats).",
    )
    created_by: Mapped[str] = mapped_column(
        VARCHAR(255),
        nullable=False,
        default="system",
        server_default="system",
        comment="User, API key, or service that made the change.",
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ────────────────────────────────────────────────────
    document = relationship("ProcessedDocument", lazy="selectin")
    source_file = relationship("File", lazy="selectin")

    __table_args__ = (
        Index("ix_diff_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<DiffLog id={self.id} type={self.diff_type} "
            f"doc={self.document_id} by={self.created_by}>"
        )

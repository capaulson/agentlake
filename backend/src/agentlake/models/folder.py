"""Folder model for hierarchical vault organization."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentlake.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Folder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represents a folder in the vault's hierarchical file system.

    Folders use a materialized path pattern for efficient subtree queries
    while also maintaining parent_id for adjacency-list traversal.
    The ``path`` column stores the full slash-separated path from root,
    e.g. ``/Partners/Acme Corp/Meeting Notes``.
    """

    __tablename__ = "folders"

    name: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment="Folder display name."
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Parent folder ID. NULL means root-level folder.",
    )
    path: Mapped[str] = mapped_column(
        VARCHAR(2048),
        nullable=False,
        default="/",
        comment="Materialized path, e.g. '/Partners/Acme Corp'.",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Optional description of the folder's contents."
    )
    created_by: Mapped[str | None] = mapped_column(
        VARCHAR(255), nullable=True, comment="User or API key that created the folder."
    )
    ai_summary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processed_documents.id", ondelete="SET NULL"),
        nullable=True,
        comment="Reference to an AI-generated summary document for this folder.",
    )

    # ── Relationships ────────────────────────────────────────────────────
    parent: Mapped[Folder | None] = relationship(
        "Folder",
        remote_side="Folder.id",
        back_populates="children",
    )
    children: Mapped[list[Folder]] = relationship(
        "Folder",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    files: Mapped[list["File"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "File",
        back_populates="folder",
        lazy="selectin",
    )
    ai_summary: Mapped["ProcessedDocument | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "ProcessedDocument",
        foreign_keys=[ai_summary_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_folders_path", "path"),
    )

    def __repr__(self) -> str:
        return f"<Folder id={self.id} name={self.name!r} path={self.path!r}>"

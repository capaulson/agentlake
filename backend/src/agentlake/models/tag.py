"""Tag and FileTag association models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentlake.models.base import Base, UUIDPrimaryKeyMixin


class Tag(UUIDPrimaryKeyMixin, Base):
    """A tag that can be assigned to one or more files.

    Tag names are always stored in lowercase for consistency.
    """

    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True, comment="Lowercase tag name."
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Human-readable description."
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="Whether this tag was created by the system (not user).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # ── Relationships ────────────────────────────────────────────────────
    files: Mapped[list["File"]] = relationship(  # noqa: F821
        "File",
        secondary="file_tags",
        back_populates="tags",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Tag id={self.id} name={self.name!r}>"


class FileTag(Base):
    """Many-to-many association between files and tags."""

    __tablename__ = "file_tags"

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    assigned_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="User or system that assigned the tag."
    )

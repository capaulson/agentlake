"""File model for raw document storage."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentlake.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FileStatus(str, enum.Enum):
    """Processing status of an uploaded file."""

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    DELETING = "deleting"


class File(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represents a raw file stored in the vault (MinIO).

    Each uploaded file gets a row here.  The ``storage_key`` points to the
    object in MinIO; all other fields are metadata extracted at upload time
    or populated by the processing pipeline.
    """

    __tablename__ = "files"

    filename: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Sanitised filename used for storage key."
    )
    original_filename: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Original filename as uploaded by the user."
    )
    content_type: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="MIME content type."
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="File size in bytes."
    )
    sha256_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 hex digest of file contents."
    )
    storage_key: Mapped[str] = mapped_column(
        String(1024), nullable=False, comment="Object key in MinIO."
    )
    uploaded_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="User or API key that uploaded the file."
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=FileStatus.PENDING.value,
        server_default=FileStatus.PENDING.value,
        comment="Processing status.",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message if processing failed."
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp."
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When processing began."
    )
    processing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When processing finished."
    )

    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Folder this file belongs to. NULL means root level.",
    )

    # ── Relationships ────────────────────────────────────────────────────
    folder: Mapped["Folder | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Folder",
        back_populates="files",
        lazy="selectin",
    )
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        "Tag",
        secondary="file_tags",
        back_populates="files",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_files_sha256_hash", "sha256_hash"),
        Index("ix_files_status", "status"),
        Index("ix_files_created_at", "created_at"),
        Index("ix_files_content_type", "content_type"),
    )

    def __repr__(self) -> str:
        return f"<File id={self.id} filename={self.original_filename!r} status={self.status}>"

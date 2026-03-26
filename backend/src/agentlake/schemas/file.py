"""Pydantic v2 schemas for files."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from agentlake.schemas.tag import TagResponse


class FileResponse(BaseModel):
    """Public representation of a file record."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    filename: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256_hash: str
    status: str
    tags: list[TagResponse] = Field(default_factory=list)
    uploaded_by: str | None
    error_message: str | None
    folder_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    processing_started_at: datetime | None
    processing_completed_at: datetime | None


class FileListParams(BaseModel):
    """Query parameters for listing files."""

    status: str | None = Field(None, description="Filter by processing status.")
    content_type: str | None = Field(None, description="Filter by MIME content type.")
    tag: str | None = Field(None, description="Filter by tag name.")
    sort_by: str = Field("created_at", description="Column to sort by.")
    sort_order: str = Field("desc", pattern="^(asc|desc)$", description="Sort direction.")
    limit: int = Field(50, ge=1, le=200, description="Maximum number of results.")
    cursor: str | None = Field(None, description="Cursor for pagination.")


class FileUploadResponse(BaseModel):
    """Response returned after a successful file upload."""

    file: FileResponse
    processing_task_id: str | None = Field(
        None, description="Celery task ID if processing was enqueued."
    )

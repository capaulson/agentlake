"""Pydantic v2 schemas for diff log entries."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DiffLogResponse(BaseModel):
    """Public representation of a diff log entry."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    document_id: uuid.UUID | None
    source_file_id: uuid.UUID
    diff_type: str
    before_text: str | None = None
    after_text: str
    justification: str
    metadata_: dict | None = Field(None, alias="metadata_")
    created_by: str
    created_at: datetime


class DiffLogListParams(BaseModel):
    """Query parameters for listing diff logs."""

    document_id: uuid.UUID | None = Field(None, description="Filter by document.")
    source_file_id: uuid.UUID | None = Field(None, description="Filter by source file.")
    diff_type: str | None = Field(None, description="Filter by diff type.")
    limit: int = Field(50, ge=1, le=200, description="Maximum number of results.")
    cursor: str | None = Field(None, description="Cursor for pagination.")

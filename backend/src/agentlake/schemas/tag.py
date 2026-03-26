"""Pydantic v2 schemas for tags."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TagCreate(BaseModel):
    """Request body for creating a tag."""

    name: str = Field(..., min_length=1, max_length=100, description="Tag name (stored lowercase).")
    description: str | None = Field(None, description="Optional description.")


class TagResponse(BaseModel):
    """Public representation of a tag."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    created_at: datetime


class TagWithCount(TagResponse):
    """Tag with the number of files it is assigned to."""

    file_count: int = Field(..., description="Number of files with this tag.")


class TagAssignment(BaseModel):
    """Request body for assigning / removing tags on a file."""

    tag_ids: list[uuid.UUID] = Field(..., description="Tag IDs to assign.")

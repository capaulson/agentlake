"""Pydantic v2 schemas for folders."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FolderCreate(BaseModel):
    """Request body for creating a new folder."""

    name: str = Field(..., min_length=1, max_length=255, description="Folder name.")
    parent_id: str | None = Field(None, description="Parent folder ID, or null for root.")
    description: str | None = Field(None, description="Optional folder description.")


class FolderUpdate(BaseModel):
    """Request body for updating folder metadata."""

    name: str | None = Field(None, min_length=1, max_length=255, description="New folder name.")
    description: str | None = Field(None, description="New description.")


class FolderMoveRequest(BaseModel):
    """Request body for moving a folder to a new parent."""

    parent_id: str | None = Field(
        None, description="New parent folder ID, or null to move to root."
    )


class FolderResponse(BaseModel):
    """Public representation of a folder record."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    path: str
    description: str | None
    created_by: str | None
    ai_summary_id: uuid.UUID | None
    file_count: int = 0
    subfolder_count: int = 0
    created_at: datetime
    updated_at: datetime


class FolderDetailResponse(BaseModel):
    """Folder details including child folders and files."""

    folder: FolderResponse
    children: list[FolderResponse]
    files: list  # FileResponse items — kept as list to avoid circular import


class FolderTreeNode(BaseModel):
    """Recursive tree node for folder hierarchy."""

    folder: FolderResponse
    children: list[FolderTreeNode]

    model_config = {"from_attributes": True}


class FileMoveRequest(BaseModel):
    """Request body for moving a file to a folder."""

    folder_id: str | None = Field(
        None, description="Target folder ID, or null to move to root."
    )

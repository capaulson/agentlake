"""Pydantic v2 schemas for processed documents, chunks, and document operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChunkResponse(BaseModel):
    """Public representation of a document chunk."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    chunk_index: int
    content: str
    summary: str | None = None
    source_locator: str
    token_count: int
    content_hash: str
    created_at: datetime


class CitationResponse(BaseModel):
    """Public representation of a citation."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    citation_index: int
    source_file_id: uuid.UUID
    chunk_index: int
    source_locator: str
    quote_snippet: str | None = None
    download_url: str | None = Field(
        None, description="Pre-built download URL for the cited source."
    )
    created_at: datetime


class DocumentResponse(BaseModel):
    """Public representation of a processed document."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    source_file_id: uuid.UUID
    title: str
    summary: str
    category: str
    body_markdown: str
    frontmatter: dict = Field(default_factory=dict)
    entities: dict | list = Field(default_factory=list)
    version: int
    is_current: bool
    processing_version: int
    created_at: datetime
    updated_at: datetime
    chunks: list[ChunkResponse] = Field(default_factory=list)
    citations: list[CitationResponse] = Field(default_factory=list)


class DocumentSummaryResponse(BaseModel):
    """Lightweight document representation for list endpoints."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    source_file_id: uuid.UUID
    title: str
    summary: str
    category: str
    version: int
    is_current: bool
    entities: dict | list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DocumentListParams(BaseModel):
    """Query parameters for listing documents."""

    category: str | None = Field(None, description="Filter by category.")
    source_file_id: uuid.UUID | None = Field(None, description="Filter by source file.")
    is_current: bool = Field(True, description="Only return current versions.")
    sort_by: str = Field("created_at", description="Column to sort by.")
    sort_order: str = Field("desc", pattern="^(asc|desc)$", description="Sort direction.")
    limit: int = Field(50, ge=1, le=200, description="Maximum number of results.")
    cursor: str | None = Field(None, description="Cursor for pagination.")


class DocumentUpdateRequest(BaseModel):
    """Request body for editing a document."""

    body_markdown: str = Field(..., min_length=1, description="Updated markdown body.")
    justification: str = Field(..., min_length=1, description="Reason for the edit.")


class DocumentHistoryEntry(BaseModel):
    """A single version entry in the document history."""

    document_id: uuid.UUID
    version: int
    is_current: bool
    title: str
    summary: str
    created_at: datetime
    edited_by: str | None = None
    justification: str | None = None
    diff_type: str | None = None


class DocumentStatsResponse(BaseModel):
    """Aggregate statistics about the document collection."""

    total_documents: int
    by_category: dict[str, int] = Field(default_factory=dict)
    by_month: list[dict] = Field(default_factory=list)
    total_chunks: int
    total_citations: int


class CategoryResponse(BaseModel):
    """Category with document count."""

    category: str
    count: int


class EntityMention(BaseModel):
    """An entity extracted from documents with mention count."""

    name: str
    entity_type: str
    mention_count: int

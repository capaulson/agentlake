"""Pydantic v2 schemas for search requests and responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    """Filters applicable to search queries."""

    category: str | None = Field(None, description="Filter by document category.")
    tags: list[str] | None = Field(None, description="Filter by tag names.")
    date_from: datetime | None = Field(None, description="Created after this date.")
    date_to: datetime | None = Field(None, description="Created before this date.")
    entities: list[str] | None = Field(None, description="Filter by entity names in JSONB.")
    source_file_id: uuid.UUID | None = Field(None, description="Filter by source file ID.")


class SearchRequest(BaseModel):
    """Request body for hybrid search."""

    q: str = Field("", description="Search query string.")
    limit: int = Field(20, ge=1, le=100, description="Maximum number of results.")
    keyword_weight: float = Field(0.4, ge=0.0, le=1.0, description="Weight for keyword results.")
    semantic_weight: float = Field(0.6, ge=0.0, le=1.0, description="Weight for semantic results.")
    filters: SearchFilters | None = Field(None, description="Optional search filters.")
    mode: str = Field(
        "hybrid",
        pattern="^(keyword|semantic|hybrid)$",
        description="Search mode: keyword, semantic, or hybrid.",
    )


class SearchHit(BaseModel):
    """A single search result."""

    id: uuid.UUID
    title: str
    summary: str
    category: str
    score: float = Field(..., description="Relevance score (higher is better).")
    snippet: str | None = Field(None, description="Highlighted text snippet.")
    source_file_id: uuid.UUID | None = None
    version: int = 1
    entities: dict | list = Field(default_factory=list)
    created_at: datetime | None = None


class SearchResponse(BaseModel):
    """Response for a search query."""

    results: list[SearchHit]
    total: int = Field(..., description="Total number of matching results.")
    search_time_ms: float = Field(..., description="Search execution time in milliseconds.")
    query: str
    mode: str

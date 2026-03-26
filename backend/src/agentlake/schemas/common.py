"""Shared Pydantic v2 response models used across all API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Meta(BaseModel):
    """Standard metadata included in every API response."""

    request_id: str = Field(..., description="Unique identifier for this request.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Server timestamp when the response was generated.",
    )


class ResponseEnvelope(BaseModel, Generic[T]):
    """Standard response wrapper: ``{"data": ..., "meta": ...}``."""

    data: T
    meta: Meta


class PaginatedMeta(BaseModel):
    """Metadata for paginated list responses."""

    request_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cursor: str | None = Field(None, description="Cursor for the next page, if any.")
    has_more: bool = Field(False, description="Whether more results exist.")
    total_count: int | None = Field(
        None, description="Total count of matching records (omitted when expensive)."
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response with cursor-based pagination."""

    data: list[T]
    meta: PaginatedMeta


class ErrorDetail(BaseModel):
    """RFC 7807 Problem Details error response body."""

    type: str = Field(..., description="URI reference identifying the problem type.")
    title: str = Field(..., description="Short human-readable summary.")
    status: int = Field(..., description="HTTP status code.")
    detail: str = Field(..., description="Human-readable explanation.")
    instance: str | None = Field(
        None, description="URI reference identifying the specific occurrence."
    )

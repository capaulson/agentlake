"""Pydantic v2 schemas for citations."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CitationResponse(BaseModel):
    """Public representation of a citation with download URL."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    document_id: uuid.UUID
    citation_index: int
    source_file_id: uuid.UUID
    chunk_index: int
    source_locator: str
    quote_snippet: str | None = None
    download_url: str = Field(
        ..., description="URL to download the cited source chunk."
    )
    created_at: datetime

    @staticmethod
    def build_download_url(source_file_id: uuid.UUID, chunk_index: int) -> str:
        """Build the canonical citation download URL.

        Uses the format: [N](/api/v1/vault/files/{file_id}/download#chunk={chunk_index})
        """
        return f"/api/v1/vault/files/{source_file_id}/download#chunk={chunk_index}"

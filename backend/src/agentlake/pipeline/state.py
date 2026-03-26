"""Pipeline state definition for the LangGraph processing graph.

With GPT-5.4's 1M context, the pipeline does single-pass full-document
analysis — one LLM call extracts everything. State is simpler but richer.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from agentlake.adapters.base import ExtractedContent
from agentlake.services.chunker import Chunk


class PipelineState(TypedDict, total=False):
    """State that flows through the processing graph."""

    # ── Input ──────────────────────────────────────────────────────────
    file_id: str
    mode: str  # "full" | "incremental"

    # ── Stage 1: Extract ───────────────────────────────────────────────
    file_bytes: bytes
    filename: str
    content_type: str
    storage_key: str
    extracted: ExtractedContent

    # ── Stage 2: Chunk (for embeddings + citations, not for LLM) ──────
    chunks: list[Chunk]

    # ── Stage 3: Full Document Analysis (single LLM call) ─────────────
    document_title: str
    document_summary: str
    category: str
    category_confidence: float
    sections: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    people: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    tags: list[str]
    dates: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    cross_references: list[str]
    key_quotes: list[str]
    classification: dict[str, Any]  # full raw classification output

    # ── Stage 4: Cite ──────────────────────────────────────────────────
    citations: list[dict[str, Any]]
    body_markdown: str

    # ── Stage 5: Embed ─────────────────────────────────────────────────
    document_embedding: list[float] | None
    chunk_embeddings: list[list[float]]

    # ── Stage 6: Store ─────────────────────────────────────────────────
    document_id: str
    frontmatter: dict[str, Any]

    # ── Metadata ───────────────────────────────────────────────────────
    current_stage: str
    progress: int
    error: str | None
    processing_started_at: str
    processing_completed_at: str | None
    llm_calls_made: Annotated[int, operator.add]
    total_tokens_used: Annotated[int, operator.add]

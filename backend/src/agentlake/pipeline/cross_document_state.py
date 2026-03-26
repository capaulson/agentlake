"""State definition for the cross-document analysis pipeline.

This pipeline runs across multiple documents to discover:
- Entity relationships that span documents
- Thematic clusters and connections
- Contradictions and corroborating evidence
- High-level insights and trends
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class DocumentSummary(TypedDict):
    """Minimal document representation for cross-doc analysis."""
    id: str
    title: str
    summary: str
    category: str
    entities: list[dict[str, str]]
    source_file_id: str


class EntityMention(TypedDict):
    """An entity found across multiple documents."""
    name: str
    canonical_name: str
    entity_type: str
    document_ids: list[str]
    mention_count: int
    contexts: list[str]  # snippet from each doc


class CrossDocRelationship(TypedDict):
    """A relationship discovered between entities across documents."""
    source_entity: str
    target_entity: str
    relationship_type: str
    description: str
    confidence: float
    evidence: list[dict[str, str]]  # [{document_id, snippet}]


class ThematicCluster(TypedDict):
    """A group of documents sharing a theme."""
    theme: str
    description: str
    document_ids: list[str]
    key_entities: list[str]


class Insight(TypedDict):
    """A high-level insight discovered across documents."""
    title: str
    description: str
    insight_type: str  # trend, contradiction, gap, connection, recommendation
    confidence: float
    supporting_documents: list[str]
    entities_involved: list[str]


class CrossDocState(TypedDict, total=False):
    """State for the cross-document analysis graph."""

    # ── Input ──────────────────────────────────────────────────────────
    trigger: str  # "scheduled" | "on_demand" | "post_processing"
    scope: str  # "all" | "recent" | "category:{name}" | "entity:{name}"
    max_documents: int
    source_document_id: str | None  # if triggered by a specific doc

    # ── Stage 1: Gather ────────────────────────────────────────────────
    documents: list[DocumentSummary]
    document_count: int

    # ── Stage 2: Entity mapping ────────────────────────────────────────
    entity_map: list[EntityMention]  # entities with cross-doc mentions
    entity_pairs: list[tuple[str, str]]  # pairs to analyze

    # ── Stage 3: Analysis (parallel branches) ──────────────────────────
    relationships: list[CrossDocRelationship]
    clusters: list[ThematicCluster]
    contradictions: list[Insight]
    connections: list[Insight]

    # ── Stage 4: Synthesis ─────────────────────────────────────────────
    insights: list[Insight]
    insight_document_markdown: str

    # ── Stage 5: Persist ───────────────────────────────────────────────
    graph_updates: int  # number of edges added/updated
    insight_document_id: str | None

    # ── Metadata ───────────────────────────────────────────────────────
    current_stage: str
    llm_calls_made: Annotated[int, operator.add]
    total_tokens_used: Annotated[int, operator.add]
    error: str | None

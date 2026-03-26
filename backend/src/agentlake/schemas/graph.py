"""Pydantic v2 schemas for the entity graph (Apache AGE)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EntityResponse(BaseModel):
    """Public representation of a graph entity vertex."""

    id: str
    name: str
    entity_type: str
    canonical_name: str
    document_count: int = 0
    first_seen_at: datetime | None = None
    properties: dict = Field(default_factory=dict)


class RelationshipResponse(BaseModel):
    """Public representation of a graph relationship edge."""

    id: str
    source: EntityResponse
    target: EntityResponse
    relationship_type: str
    description: str = ""
    confidence: float = 0.0
    weight: int = 1
    source_document_id: str | None = None


class NeighborResponse(BaseModel):
    """Entity with its immediate neighborhood."""

    entity: EntityResponse
    neighbors: list[EntityResponse] = Field(default_factory=list)
    relationships: list[RelationshipResponse] = Field(default_factory=list)
    depth: int = 1


class GraphPathResponse(BaseModel):
    """A path between two entities in the graph."""

    path: list[EntityResponse] = Field(default_factory=list)
    relationships: list[RelationshipResponse] = Field(default_factory=list)
    total_weight: float = 0.0


class GraphSearchParams(BaseModel):
    """Query parameters for searching entities."""

    q: str = Field(..., min_length=1, description="Search query for entity names.")
    entity_type: str | None = Field(None, description="Filter by entity type.")
    limit: int = Field(20, ge=1, le=100, description="Maximum number of results.")


class GraphStatsResponse(BaseModel):
    """Aggregate statistics about the entity graph."""

    total_entities: int = 0
    total_relationships: int = 0
    entities_by_type: dict[str, int] = Field(default_factory=dict)
    relationships_by_type: dict[str, int] = Field(default_factory=dict)

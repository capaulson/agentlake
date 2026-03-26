"""Graph router — entity search, relationships, and statistics.

Reads entity and relationship data from ProcessedDocument.entities (JSONB)
and ProcessedDocument.frontmatter->'relationships' (JSONB). This is more
reliable than Apache AGE and uses the rich data from GPT-5.4 extraction.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.core.auth import require_role
from agentlake.core.database import get_db
from agentlake.schemas.common import Meta, ResponseEnvelope

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


def _request_id() -> str:
    import uuid
    return str(uuid.uuid4())


@router.get("/stats", response_model=ResponseEnvelope[dict])
async def get_graph_stats(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),
):
    """Graph statistics — entity and relationship counts."""
    result = await db.execute(text("""
        WITH entity_data AS (
            SELECT jsonb_array_elements(entities) as entity
            FROM processed_documents WHERE is_current = true
        ),
        rel_data AS (
            SELECT jsonb_array_elements(frontmatter->'relationships') as rel
            FROM processed_documents WHERE is_current = true AND frontmatter->'relationships' IS NOT NULL
        )
        SELECT
            (SELECT count(*) FROM entity_data) as total_entities,
            (SELECT count(*) FROM rel_data) as total_relationships,
            (SELECT jsonb_object_agg(type, cnt) FROM (
                SELECT entity->>'type' as type, count(*) as cnt FROM entity_data GROUP BY entity->>'type'
            ) t) as entities_by_type,
            (SELECT jsonb_object_agg(type, cnt) FROM (
                SELECT rel->>'type' as type, count(*) as cnt FROM rel_data GROUP BY rel->>'type'
            ) t) as relationships_by_type
    """))
    row = result.fetchone()

    return ResponseEnvelope(
        data={
            "total_entities": row[0] if row else 0,
            "total_relationships": row[1] if row else 0,
            "entities_by_type": row[2] if row and row[2] else {},
            "relationships_by_type": row[3] if row and row[3] else {},
        },
        meta=Meta(request_id=_request_id()),
    )


@router.get("/search", response_model=ResponseEnvelope[list])
async def search_entities(
    q: str = Query(..., description="Entity name to search"),
    entity_type: str | None = Query(None),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),
):
    """Search entities across all documents."""
    type_filter = ""
    if entity_type:
        type_filter = f"AND entity->>'type' = '{entity_type}'"

    result = await db.execute(text(f"""
        WITH entity_data AS (
            SELECT
                pd.id as doc_id,
                pd.title as doc_title,
                jsonb_array_elements(pd.entities) as entity
            FROM processed_documents pd
            WHERE pd.is_current = true
        )
        SELECT
            entity->>'name' as name,
            entity->>'type' as type,
            entity->>'context' as context,
            count(DISTINCT doc_id) as document_count,
            sum((entity->>'mentions')::int) as total_mentions,
            array_agg(DISTINCT doc_title) as documents
        FROM entity_data
        WHERE entity->>'name' ILIKE :pattern {type_filter}
        GROUP BY entity->>'name', entity->>'type', entity->>'context'
        ORDER BY document_count DESC, total_mentions DESC
        LIMIT :lim
    """), {"pattern": f"%{q}%", "lim": limit})

    entities = []
    for row in result.fetchall():
        entities.append({
            "name": row[0],
            "type": row[1],
            "context": row[2],
            "document_count": row[3],
            "total_mentions": row[4] or row[3],
            "documents": list(row[5])[:5] if row[5] else [],
        })

    return ResponseEnvelope(data=entities, meta=Meta(request_id=_request_id()))


@router.get("/entity/{name}", response_model=ResponseEnvelope[dict])
async def get_entity(
    name: str,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),
):
    """Get entity details with all relationships and documents."""
    # Find the entity across documents
    result = await db.execute(text("""
        WITH matches AS (
            SELECT pd.id as doc_id, pd.title, pd.source_file_id,
                   jsonb_array_elements(pd.entities) as entity
            FROM processed_documents pd WHERE pd.is_current = true
        )
        SELECT entity->>'name', entity->>'type', entity->>'context',
               count(DISTINCT doc_id), array_agg(DISTINCT title)
        FROM matches
        WHERE entity->>'name' ILIKE :name
        GROUP BY entity->>'name', entity->>'type', entity->>'context'
        LIMIT 1
    """), {"name": f"%{name}%"})
    row = result.fetchone()
    if not row:
        return ResponseEnvelope(data={"error": "Entity not found"}, meta=Meta(request_id=_request_id()))

    # Get relationships involving this entity
    rels_result = await db.execute(text("""
        SELECT rel->>'source' as source, rel->>'target' as target,
               rel->>'type' as type, rel->>'description' as description,
               (rel->>'confidence')::float as confidence,
               rel->>'evidence' as evidence,
               pd.title as doc_title
        FROM processed_documents pd,
             jsonb_array_elements(pd.frontmatter->'relationships') as rel
        WHERE pd.is_current = true
          AND pd.frontmatter->'relationships' IS NOT NULL
          AND (rel->>'source' ILIKE :name OR rel->>'target' ILIKE :name)
        ORDER BY confidence DESC
        LIMIT 30
    """), {"name": f"%{name}%"})

    relationships = []
    for r in rels_result.fetchall():
        relationships.append({
            "source": r[0], "target": r[1], "type": r[2],
            "description": r[3], "confidence": r[4],
            "evidence": r[5], "document": r[6],
        })

    return ResponseEnvelope(
        data={
            "name": row[0],
            "type": row[1],
            "context": row[2],
            "document_count": row[3],
            "documents": list(row[4])[:10] if row[4] else [],
            "relationships": relationships,
        },
        meta=Meta(request_id=_request_id()),
    )


@router.get("/entity/{name}/neighbors", response_model=ResponseEnvelope[dict])
async def get_entity_neighbors(
    name: str,
    depth: int = Query(1, le=3),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),
):
    """Get entities connected to the given entity."""
    result = await db.execute(text("""
        SELECT rel->>'source' as source, rel->>'target' as target,
               rel->>'type' as type, rel->>'description' as desc,
               (rel->>'confidence')::float as confidence
        FROM processed_documents pd,
             jsonb_array_elements(pd.frontmatter->'relationships') as rel
        WHERE pd.is_current = true
          AND pd.frontmatter->'relationships' IS NOT NULL
          AND (rel->>'source' ILIKE :name OR rel->>'target' ILIKE :name)
        ORDER BY confidence DESC
        LIMIT 50
    """), {"name": f"%{name}%"})

    nodes = {name: {"name": name, "type": "unknown", "connections": 0}}
    edges = []
    for r in result.fetchall():
        src, tgt = r[0], r[1]
        other = tgt if name.lower() in src.lower() else src
        if other not in nodes:
            nodes[other] = {"name": other, "type": "unknown", "connections": 0}
        nodes[other]["connections"] += 1
        nodes[name]["connections"] += 1
        edges.append({"source": src, "target": tgt, "type": r[2], "description": r[3], "confidence": r[4]})

    return ResponseEnvelope(
        data={"center": name, "nodes": list(nodes.values()), "edges": edges},
        meta=Meta(request_id=_request_id()),
    )


@router.get("/entity/{name}/documents", response_model=ResponseEnvelope[list])
async def get_entity_documents(
    name: str,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),
):
    """Get documents mentioning an entity."""
    result = await db.execute(text("""
        SELECT pd.id, pd.title, pd.category, pd.summary, pd.created_at
        FROM processed_documents pd,
             jsonb_array_elements(pd.entities) as entity
        WHERE pd.is_current = true
          AND entity->>'name' ILIKE :name
        GROUP BY pd.id, pd.title, pd.category, pd.summary, pd.created_at
        ORDER BY pd.created_at DESC
        LIMIT 20
    """), {"name": f"%{name}%"})

    return ResponseEnvelope(
        data=[{"id": str(r[0]), "title": r[1], "category": r[2], "summary": (r[3] or "")[:200], "created_at": r[4].isoformat()} for r in result.fetchall()],
        meta=Meta(request_id=_request_id()),
    )


@router.get("/relationships", response_model=ResponseEnvelope[list])
async def list_relationships(
    relationship_type: str | None = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),
):
    """List all relationships across documents."""
    type_filter = ""
    if relationship_type:
        type_filter = f"AND rel->>'type' = '{relationship_type}'"

    result = await db.execute(text(f"""
        SELECT rel->>'source' as source, rel->>'target' as target,
               rel->>'type' as type, rel->>'description' as desc,
               (rel->>'confidence')::float as confidence,
               pd.title as document
        FROM processed_documents pd,
             jsonb_array_elements(pd.frontmatter->'relationships') as rel
        WHERE pd.is_current = true
          AND pd.frontmatter->'relationships' IS NOT NULL
          {type_filter}
        ORDER BY confidence DESC
        LIMIT :lim
    """), {"lim": limit})

    return ResponseEnvelope(
        data=[{"source": r[0], "target": r[1], "type": r[2], "description": r[3], "confidence": r[4], "document": r[5]} for r in result.fetchall()],
        meta=Meta(request_id=_request_id()),
    )

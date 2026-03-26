"""Discovery router — agent-friendly endpoints for data lake exploration.

Provides overview, schema, and summary endpoints designed for external
agents (MCP, Claude, custom) to understand the data lake's contents and
capabilities without reading documentation.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake import __version__
from agentlake.core.auth import require_role
from agentlake.core.database import get_db
from agentlake.models.document import ProcessedDocument
from agentlake.models.file import File
from agentlake.models.tag import FileTag, Tag
from agentlake.schemas.common import Meta, ResponseEnvelope
from agentlake.services.documents import DocumentService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/discover", tags=["discover"])


def _request_id() -> str:
    return structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))


# ── Discovery Overview ───────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=ResponseEnvelope[dict],
    summary="Agent discovery endpoint",
)
async def discover(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Agent discovery endpoint -- overview of the data lake.

    Returns the lake's name, version, capabilities, and summary statistics
    so an agent can understand what is available without prior knowledge.
    """
    # Total files
    file_count_result = await db.execute(
        select(func.count()).select_from(File).where(File.deleted_at.is_(None))
    )
    total_files = file_count_result.scalar() or 0

    # Total documents
    doc_count_result = await db.execute(
        select(func.count())
        .select_from(ProcessedDocument)
        .where(ProcessedDocument.is_current.is_(True))
    )
    total_documents = doc_count_result.scalar() or 0

    # Categories
    cat_result = await db.execute(
        select(ProcessedDocument.category, func.count().label("count"))
        .where(ProcessedDocument.is_current.is_(True))
        .group_by(ProcessedDocument.category)
        .order_by(func.count().desc())
    )
    categories = [row.category for row in cat_result if row.category]

    # Tags
    tag_result = await db.execute(
        select(Tag.name).order_by(Tag.name)
    )
    tag_names = [row[0] for row in tag_result]

    return ResponseEnvelope(
        data={
            "name": "AgentLake",
            "description": (
                "Distributed, agent-friendly data lake with LLM-powered processing, "
                "searchable markdown with citation traceability, and entity graph."
            ),
            "version": __version__,
            "capabilities": [
                "search",
                "upload",
                "graph",
                "citations",
                "edit",
                "streaming",
                "incremental_reprocessing",
            ],
            "total_files": total_files,
            "total_documents": total_documents,
            "categories": categories,
            "tags": tag_names,
            "endpoints": {
                "vault": "/api/v1/vault",
                "query": "/api/v1/query",
                "graph": "/api/v1/graph",
                "discover": "/api/v1/discover",
                "admin": "/api/v1/admin",
                "stream": "/api/v1/stream",
                "health": "/api/v1/health",
                "docs": "/api/docs",
            },
        },
        meta=Meta(request_id=_request_id()),
    )


# ── Schema ───────────────────────────────────────────────────────────────────


@router.get(
    "/schema",
    response_model=ResponseEnvelope[dict],
    summary="Data ontology schema",
)
async def get_schema(
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Return the Common Data Ontology schema for processed documents.

    Describes the YAML frontmatter fields, document structure, entity types,
    and relationship types that AgentLake uses.
    """
    schema = {
        "document": {
            "title": "string (required) - Document title",
            "summary": "string (required) - Brief summary",
            "category": "string (required) - Document category",
            "body_markdown": "string (required) - Full markdown content",
            "frontmatter": {
                "description": "YAML frontmatter conforming to the ontology",
                "fields": {
                    "source_file": "UUID of the original file",
                    "processing_version": "int - pipeline version used",
                    "entities": "list of {name, type} objects",
                    "relationships": "list of {source_entity, target_entity, relationship_type}",
                    "keywords": "list of extracted keywords",
                    "language": "ISO 639-1 language code",
                    "confidence": "float 0-1, processing confidence",
                },
            },
            "entities": "list of {name: str, type: str} - extracted entities",
            "citations": "list of {citation_index, source_file_id, chunk_index}",
        },
        "entity_types": [
            "PERSON",
            "ORG",
            "LOCATION",
            "DATE",
            "PRODUCT",
            "EVENT",
            "TECHNOLOGY",
            "REGULATION",
            "FINANCIAL",
            "OTHER",
        ],
        "relationship_types": [
            "WORKS_FOR",
            "LOCATED_IN",
            "OWNS",
            "PARTNER_OF",
            "SUBSIDIARY_OF",
            "REGULATES",
            "COMPETES_WITH",
            "SUPPLIES_TO",
            "RELATED_TO",
        ],
        "citation_format": "[N](/api/v1/vault/files/{file_id}/download#chunk={chunk_index})",
    }

    return ResponseEnvelope(
        data=schema,
        meta=Meta(request_id=_request_id()),
    )


# ── Tags ─────────────────────────────────────────────────────────────────────


@router.get(
    "/tags",
    response_model=ResponseEnvelope[list[dict]],
    summary="List all tags with counts",
)
async def get_tags(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[list[dict]]:
    """Return all tags with the number of files each is assigned to."""
    stmt = (
        select(
            Tag.name,
            Tag.description,
            func.count(FileTag.file_id).label("file_count"),
        )
        .outerjoin(FileTag, FileTag.tag_id == Tag.id)
        .group_by(Tag.id, Tag.name, Tag.description)
        .order_by(func.count(FileTag.file_id).desc())
    )
    result = await db.execute(stmt)

    tags = [
        {
            "name": row.name,
            "description": row.description,
            "file_count": row.file_count,
        }
        for row in result
    ]

    return ResponseEnvelope(
        data=tags,
        meta=Meta(request_id=_request_id()),
    )


# ── Categories ───────────────────────────────────────────────────────────────


@router.get(
    "/categories",
    response_model=ResponseEnvelope[list[dict]],
    summary="List document categories with counts",
)
async def get_categories(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[list[dict]]:
    """Return all document categories with their counts."""
    doc_service = DocumentService(db=db)
    categories = await doc_service.get_categories()

    return ResponseEnvelope(
        data=categories,
        meta=Meta(request_id=_request_id()),
    )


# ── Statistics ───────────────────────────────────────────────────────────────


@router.get(
    "/stats",
    response_model=ResponseEnvelope[dict],
    summary="Aggregate data lake statistics",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Get aggregate statistics: file counts, document counts, categories, etc."""
    # Files by status
    file_status_stmt = (
        select(File.status, func.count().label("count"))
        .where(File.deleted_at.is_(None))
        .group_by(File.status)
    )
    file_status_result = await db.execute(file_status_stmt)
    files_by_status = {row.status: row.count for row in file_status_result}

    # Document stats
    doc_service = DocumentService(db=db)
    doc_stats = await doc_service.get_stats()

    return ResponseEnvelope(
        data={
            "files_by_status": files_by_status,
            "total_files": sum(files_by_status.values()),
            **doc_stats,
        },
        meta=Meta(request_id=_request_id()),
    )

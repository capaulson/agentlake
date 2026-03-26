"""Query router — search, document CRUD, stats, and entity listing.

Provides the primary data access layer for searching processed documents,
reading/editing individual documents, browsing categories and entities,
and fetching aggregate statistics.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.config import get_settings
from agentlake.core.auth import require_role
from agentlake.core.database import get_db
from agentlake.core.exceptions import NotFoundError
from agentlake.schemas.citation import CitationResponse
from agentlake.schemas.common import Meta, PaginatedMeta, PaginatedResponse, ResponseEnvelope
from agentlake.schemas.document import (
    CategoryResponse,
    DocumentHistoryEntry,
    DocumentListParams,
    DocumentResponse,
    DocumentStatsResponse,
    DocumentSummaryResponse,
    DocumentUpdateRequest,
    EntityMention,
)
from agentlake.schemas.search import SearchHit, SearchResponse
from agentlake.services.documents import DocumentService
from agentlake.services.llm_client import LLMClient
from agentlake.services.search import SearchService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/query", tags=["query"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _request_id() -> str:
    return structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))


def _make_llm_client() -> LLMClient:
    settings = get_settings()
    return LLMClient(
        gateway_url=settings.LLM_GATEWAY_URL,
        service_token=settings.LLM_GATEWAY_SERVICE_TOKEN,
        service_name="api",
    )


# ── Search ───────────────────────────────────────────────────────────────────


@router.get(
    "/search",
    response_model=ResponseEnvelope[SearchResponse],
    summary="Search processed documents",
)
async def search(
    q: str = Query("", description="Search query string"),
    search_type: str = Query(
        "hybrid", pattern="^(keyword|semantic|hybrid)$", description="Search mode"
    ),
    category: str | None = Query(None, description="Filter by category"),
    tags: list[str] | None = Query(None, description="Filter by tag names"),
    entities: list[str] | None = Query(None, description="Filter by entity names"),
    date_from: date | None = Query(None, description="Created after this date"),
    date_to: date | None = Query(None, description="Created before this date"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    keyword_weight: float = Query(0.4, ge=0.0, le=1.0),
    semantic_weight: float = Query(0.6, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[SearchResponse]:
    """Search processed documents using keyword, semantic, or hybrid mode.

    The hybrid mode (default) runs keyword and semantic searches in parallel,
    then merges results using Reciprocal Rank Fusion (RRF).
    """
    llm_client = _make_llm_client()
    search_service = SearchService(db=db, llm_client=llm_client)

    # Build filters dict
    filters: dict = {}
    if category:
        filters["category"] = category
    if tags:
        filters["tags"] = tags
    if entities:
        filters["entities"] = entities
    if date_from:
        filters["date_from"] = datetime.combine(date_from, datetime.min.time())
    if date_to:
        filters["date_to"] = datetime.combine(date_to, datetime.max.time())

    if search_type == "keyword":
        raw_results = await search_service.keyword_search(
            query=q, limit=limit, filters=filters or None
        )
        response = SearchResponse(
            results=[SearchHit(**r) for r in raw_results],
            total=len(raw_results),
            search_time_ms=0.0,
            query=q,
            mode="keyword",
        )
    elif search_type == "semantic":
        raw_results = await search_service.semantic_search(
            query=q, limit=limit, filters=filters or None
        )
        response = SearchResponse(
            results=[SearchHit(**r) for r in raw_results],
            total=len(raw_results),
            search_time_ms=0.0,
            query=q,
            mode="semantic",
        )
    else:
        raw = await search_service.hybrid_search(
            query=q,
            limit=limit,
            keyword_weight=keyword_weight,
            semantic_weight=semantic_weight,
            filters=filters or None,
        )
        response = SearchResponse(
            results=[SearchHit(**r) for r in raw["results"]],
            total=raw["total"],
            search_time_ms=raw["search_time_ms"],
            query=raw["query"],
            mode=raw["mode"],
        )

    return ResponseEnvelope(
        data=response,
        meta=Meta(request_id=_request_id()),
    )


# ── List Documents ───────────────────────────────────────────────────────────


@router.get(
    "/documents",
    response_model=PaginatedResponse[DocumentSummaryResponse],
    summary="List processed documents",
)
async def list_documents(
    params: DocumentListParams = Depends(),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> PaginatedResponse[DocumentSummaryResponse]:
    """List processed documents with cursor-based pagination and filtering."""
    doc_service = DocumentService(db=db)
    documents, next_cursor, has_more = await doc_service.list_documents(
        category=params.category,
        source_file_id=params.source_file_id,
        is_current=params.is_current,
        limit=params.limit,
        cursor=params.cursor,
        sort_by=params.sort_by,
        sort_order=params.sort_order,
    )

    return PaginatedResponse(
        data=[DocumentSummaryResponse.model_validate(d) for d in documents],
        meta=PaginatedMeta(
            request_id=_request_id(),
            cursor=next_cursor,
            has_more=has_more,
        ),
    )


# ── Get Document ─────────────────────────────────────────────────────────────


@router.get(
    "/documents/{document_id}",
    response_model=ResponseEnvelope[DocumentResponse],
    summary="Get a processed document by ID",
)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[DocumentResponse]:
    """Retrieve a single processed document with chunks and citations."""
    doc_service = DocumentService(db=db)
    doc = await doc_service.get_document(document_id)
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    return ResponseEnvelope(
        data=DocumentResponse.model_validate(doc),
        meta=Meta(request_id=_request_id()),
    )


# ── Document History ─────────────────────────────────────────────────────────


@router.get(
    "/documents/{document_id}/history",
    response_model=ResponseEnvelope[list[DocumentHistoryEntry]],
    summary="Get version history of a document",
)
async def get_document_history(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[list[DocumentHistoryEntry]]:
    """Get the complete version history for a document, including diff metadata."""
    doc_service = DocumentService(db=db)
    history = await doc_service.get_document_history(document_id)

    entries = [DocumentHistoryEntry(**h) for h in history]

    return ResponseEnvelope(
        data=entries,
        meta=Meta(request_id=_request_id()),
    )


# ── Update Document ──────────────────────────────────────────────────────────


@router.put(
    "/documents/{document_id}",
    response_model=ResponseEnvelope[DocumentResponse],
    summary="Edit a processed document",
)
async def update_document(
    document_id: uuid.UUID,
    body: DocumentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[DocumentResponse]:
    """Edit a document's markdown body, creating a new version.

    Every edit produces a DiffLog entry (critical invariant).
    """
    llm_client = _make_llm_client()
    doc_service = DocumentService(db=db, llm_client=llm_client)

    edited_by = api_key.name if hasattr(api_key, "name") else str(api_key.id)
    new_doc = await doc_service.update_document(
        document_id=document_id,
        body_markdown=body.body_markdown,
        justification=body.justification,
        edited_by=edited_by,
    )

    return ResponseEnvelope(
        data=DocumentResponse.model_validate(new_doc),
        meta=Meta(request_id=_request_id()),
    )


# ── Document Citations ───────────────────────────────────────────────────────


@router.get(
    "/documents/{document_id}/citations",
    response_model=ResponseEnvelope[list[CitationResponse]],
    summary="Get citations for a document",
)
async def get_document_citations(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[list[CitationResponse]]:
    """Get all citations for a document with downloadable source links."""
    doc_service = DocumentService(db=db)
    citations = await doc_service.get_citations(document_id)

    citation_responses = []
    for c in citations:
        download_url = CitationResponse.build_download_url(
            c.source_file_id, c.chunk_index
        )
        citation_responses.append(
            CitationResponse(
                id=c.id,
                document_id=document_id,
                citation_index=c.citation_index,
                source_file_id=c.source_file_id,
                chunk_index=c.chunk_index,
                source_locator=c.source_locator,
                quote_snippet=c.quote_snippet,
                download_url=download_url,
                created_at=c.created_at,
            )
        )

    return ResponseEnvelope(
        data=citation_responses,
        meta=Meta(request_id=_request_id()),
    )


# ── Statistics ───────────────────────────────────────────────────────────────


@router.get(
    "/stats",
    response_model=ResponseEnvelope[DocumentStatsResponse],
    summary="Get collection statistics",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[DocumentStatsResponse]:
    """Get aggregate statistics about the document collection."""
    doc_service = DocumentService(db=db)
    stats = await doc_service.get_stats()

    return ResponseEnvelope(
        data=DocumentStatsResponse(**stats),
        meta=Meta(request_id=_request_id()),
    )


# ── Categories ───────────────────────────────────────────────────────────────


@router.get(
    "/categories",
    response_model=ResponseEnvelope[list[CategoryResponse]],
    summary="List document categories",
)
async def get_categories(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[list[CategoryResponse]]:
    """Get all categories with their document counts."""
    doc_service = DocumentService(db=db)
    categories = await doc_service.get_categories()

    return ResponseEnvelope(
        data=[CategoryResponse(**c) for c in categories],
        meta=Meta(request_id=_request_id()),
    )


# ── Entities ─────────────────────────────────────────────────────────────────


@router.get(
    "/entities",
    response_model=ResponseEnvelope[list[EntityMention]],
    summary="List entities extracted from documents",
)
async def get_entities(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[list[EntityMention]]:
    """Get all unique entities with mention counts from JSONB data."""
    doc_service = DocumentService(db=db)
    entities = await doc_service.get_entities()

    return ResponseEnvelope(
        data=[EntityMention(**e) for e in entities],
        meta=Meta(request_id=_request_id()),
    )


# ── Agentic Search ───────────────────────────────────────────────────────


@router.get(
    "/ask",
    response_model=ResponseEnvelope[dict],
    summary="Ask a question (agentic search)",
)
async def agentic_search(
    q: str = Query(..., description="Natural language question"),
    max_sources: int = Query(10, le=20),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Ask a natural language question and get a synthesized answer with sources.

    Uses a LangGraph pipeline that:
    1. Searches the corpus for relevant documents
    2. Retrieves and evaluates relevant chunks
    3. Optionally runs follow-up searches if needed
    4. Synthesizes a comprehensive answer with inline citations
    """
    from agentlake.pipeline.agentic_search import agentic_search_graph

    result = await agentic_search_graph.ainvoke({
        "question": q,
        "search_type": "hybrid",
        "max_sources": max_sources,
        "llm_calls_made": 0,
        "total_tokens_used": 0,
    })

    return ResponseEnvelope(
        data=result.get("formatted_response", {}),
        meta=Meta(request_id=_request_id()),
    )


# ── Knowledge Memory ─────────────────────────────────────────────────────


@router.get(
    "/knowledge",
    response_model=ResponseEnvelope[dict],
    summary="Get institutional knowledge memory",
)
async def get_knowledge(
    limit: int = Query(50, le=200),
    theme: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Get the institutional knowledge built from questions asked of the data lake."""
    from sqlalchemy import select, text
    from agentlake.models.knowledge import KnowledgeMemory

    query = (
        select(KnowledgeMemory)
        .order_by(KnowledgeMemory.created_at.desc())
        .limit(limit)
    )
    if theme:
        query = query.where(KnowledgeMemory.theme == theme)

    result = await db.execute(query)
    memories = result.scalars().all()

    # Get theme summary
    theme_result = await db.execute(text("""
        SELECT theme, count(*) as count,
               avg(confidence) as avg_confidence,
               max(created_at) as last_asked
        FROM knowledge_memory
        WHERE theme IS NOT NULL
        GROUP BY theme
        ORDER BY count DESC
    """))
    themes = [
        {"theme": r[0], "count": r[1], "avg_confidence": round(float(r[2]), 2), "last_asked": r[3].isoformat() if r[3] else None}
        for r in theme_result.fetchall()
    ]

    # Get all follow-up questions the system wants to explore
    followup_result = await db.execute(text("""
        SELECT follow_up_questions, theme, created_at
        FROM knowledge_memory
        WHERE jsonb_array_length(follow_up_questions) > 0
        ORDER BY created_at DESC
        LIMIT 20
    """))
    system_curiosity = []
    seen = set()
    for row in followup_result.fetchall():
        fqs = row[0] if isinstance(row[0], list) else []
        for q in fqs:
            if isinstance(q, str) and q not in seen:
                seen.add(q)
                system_curiosity.append({"question": q, "from_theme": row[1], "generated_at": row[2].isoformat() if row[2] else None})

    # Stats
    stats_result = await db.execute(text("""
        SELECT
            count(*) as total,
            count(DISTINCT theme) as themes,
            avg(confidence) as avg_confidence,
            sum(tokens_used) as total_tokens,
            count(*) FILTER (WHERE led_to_analysis) as led_to_analysis
        FROM knowledge_memory
    """))
    stats_row = stats_result.fetchone()

    return ResponseEnvelope(
        data={
            "memories": [
                {
                    "id": str(m.id),
                    "question": m.question,
                    "answer": (m.answer or "")[:500],
                    "confidence": m.confidence,
                    "theme": m.theme,
                    "intent": m.intent,
                    "entities_mentioned": m.entities_mentioned,
                    "discoveries": m.discoveries,
                    "follow_up_questions": m.follow_up_questions,
                    "related_questions": m.related_question_ids,
                    "sources_used": m.sources_used,
                    "led_to_analysis": m.led_to_analysis,
                    "asked_by": m.asked_by,
                    "created_at": m.created_at.isoformat(),
                }
                for m in memories
            ],
            "themes": themes,
            "system_curiosity": system_curiosity[:20],
            "stats": {
                "total_questions": stats_row[0] if stats_row else 0,
                "unique_themes": stats_row[1] if stats_row else 0,
                "avg_confidence": round(float(stats_row[2]), 2) if stats_row and stats_row[2] else 0,
                "total_tokens": stats_row[3] if stats_row else 0,
                "questions_triggering_analysis": stats_row[4] if stats_row else 0,
            },
        },
        meta=Meta(request_id=_request_id()),
    )

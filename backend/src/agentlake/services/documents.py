"""Document service — CRUD, versioning, history, and statistics.

Handles processed document lifecycle including reads, edits with
mandatory diff logging, version history, and aggregate statistics.
"""

from __future__ import annotations

import uuid
from base64 import b64decode, b64encode
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentlake.core.exceptions import LLMGatewayError, NotFoundError
from agentlake.models.diff_log import DiffLog, DiffType
from agentlake.models.document import Citation, DocumentChunk, ProcessedDocument
from agentlake.services.diff import DiffService
from agentlake.services.llm_client import LLMClient

logger = structlog.get_logger(__name__)


class DocumentService:
    """Service for managing processed documents.

    Args:
        db: Async SQLAlchemy session.
        llm_client: Optional LLM client for re-embedding on edits.
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.db = db
        self.llm_client = llm_client
        self._diff_service = DiffService(db)

    # ── Single Document ───────────────────────────────────────────────────

    async def get_document(
        self, document_id: uuid.UUID
    ) -> ProcessedDocument | None:
        """Get a document with chunks and citations eagerly loaded.

        Args:
            document_id: The document UUID.

        Returns:
            The ProcessedDocument or None if not found.
        """
        stmt = (
            select(ProcessedDocument)
            .where(ProcessedDocument.id == document_id)
            .options(
                selectinload(ProcessedDocument.chunks),
                selectinload(ProcessedDocument.citations),
                selectinload(ProcessedDocument.source_file),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ── List Documents ────────────────────────────────────────────────────

    async def list_documents(
        self,
        category: str | None = None,
        source_file_id: uuid.UUID | None = None,
        is_current: bool = True,
        limit: int = 50,
        cursor: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[ProcessedDocument], str | None, bool]:
        """List documents with filtering and cursor-based pagination.

        Args:
            category: Optional category filter.
            source_file_id: Optional source file filter.
            is_current: Whether to return only current versions.
            limit: Maximum number of results per page.
            cursor: Opaque cursor for pagination (base64-encoded timestamp).
            sort_by: Column to sort by (created_at or updated_at).
            sort_order: Sort direction (asc or desc).

        Returns:
            Tuple of (documents, next_cursor, has_more).
        """
        # Validate sort column
        sort_column = getattr(ProcessedDocument, sort_by, None)
        if sort_column is None:
            sort_column = ProcessedDocument.created_at

        stmt = select(ProcessedDocument).where(
            ProcessedDocument.is_current.is_(is_current)
        )

        if category:
            stmt = stmt.where(ProcessedDocument.category == category)
        if source_file_id:
            stmt = stmt.where(ProcessedDocument.source_file_id == source_file_id)

        # Apply cursor-based pagination
        if cursor:
            try:
                cursor_value = b64decode(cursor).decode("utf-8")
                cursor_dt = datetime.fromisoformat(cursor_value)
                if sort_order == "desc":
                    stmt = stmt.where(sort_column < cursor_dt)
                else:
                    stmt = stmt.where(sort_column > cursor_dt)
            except (ValueError, UnicodeDecodeError):
                logger.warning("invalid_pagination_cursor", cursor=cursor)

        # Apply ordering
        if sort_order == "desc":
            stmt = stmt.order_by(sort_column.desc())
        else:
            stmt = stmt.order_by(sort_column.asc())

        # Fetch one extra to detect has_more
        stmt = stmt.limit(limit + 1)

        result = await self.db.execute(stmt)
        documents = list(result.scalars().all())

        has_more = len(documents) > limit
        if has_more:
            documents = documents[:limit]

        # Build next cursor from the last document's sort value
        next_cursor: str | None = None
        if has_more and documents:
            last_value = getattr(documents[-1], sort_by)
            if isinstance(last_value, datetime):
                next_cursor = b64encode(
                    last_value.isoformat().encode("utf-8")
                ).decode("ascii")

        logger.debug(
            "list_documents",
            count=len(documents),
            category=category,
            has_more=has_more,
        )

        return documents, next_cursor, has_more

    # ── Update Document (with Diff Logging) ───────────────────────────────

    async def update_document(
        self,
        document_id: uuid.UUID,
        body_markdown: str,
        justification: str,
        edited_by: str = "user",
    ) -> ProcessedDocument:
        """Edit a document: create a new version, log the diff, re-embed.

        Critical invariant: every edit produces a DiffLog entry.

        Args:
            document_id: The current document to edit.
            body_markdown: The new markdown body content.
            justification: Reason for the edit.
            edited_by: Who made the change (user, admin, pipeline, etc.).

        Returns:
            The newly created document version.

        Raises:
            NotFoundError: If the document does not exist.
        """
        current = await self.get_document(document_id)
        if current is None:
            raise NotFoundError(f"Document {document_id} not found")

        if not current.is_current:
            raise NotFoundError(
                f"Document {document_id} is not the current version"
            )

        # 1. Mark current version as non-current
        current.is_current = False

        # 2. Create new version
        new_doc = ProcessedDocument(
            source_file_id=current.source_file_id,
            title=current.title,
            summary=current.summary,
            category=current.category,
            body_markdown=body_markdown,
            frontmatter=current.frontmatter,
            entities=current.entities,
            embedding=current.embedding,  # Will be replaced below if possible
            search_vector=None,  # Will be regenerated by trigger/update
            version=current.version + 1,
            is_current=True,
            processing_version=current.processing_version,
        )
        self.db.add(new_doc)

        # Flush to get the new document ID
        await self.db.flush()

        # 3. Compute diff and create DiffLog entry via DiffService
        diff_ops = DiffService.compute_diff(
            current.body_markdown, body_markdown
        )
        await self._diff_service.create_edit_diff(
            document_id=new_doc.id,
            source_file_id=current.source_file_id,
            before_text=current.body_markdown,
            after_text=body_markdown,
            justification=justification,
            created_by=edited_by,
            metadata={"diff_ops": diff_ops, "version_from": current.version},
        )

        # 4. Re-generate embedding for the new content
        if self.llm_client is not None:
            try:
                embeddings = await self.llm_client.embed([body_markdown[:8000]])
                new_doc.embedding = embeddings[0]
            except LLMGatewayError:
                logger.warning(
                    "document_update_embedding_failed",
                    document_id=str(new_doc.id),
                )

        # 5. Update the search vector via raw SQL (tsvector needs text input)
        await self.db.flush()
        await self.db.execute(
            text(
                "UPDATE processed_documents "
                "SET search_vector = to_tsvector('english', :title || ' ' || :body) "
                "WHERE id = :doc_id"
            ),
            {
                "title": new_doc.title,
                "body": body_markdown,
                "doc_id": str(new_doc.id),
            },
        )

        logger.info(
            "document_updated",
            document_id=str(new_doc.id),
            version=new_doc.version,
            edited_by=edited_by,
        )

        return new_doc

    # ── Document History ──────────────────────────────────────────────────

    async def get_document_history(
        self, document_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Get all versions and diff logs for a document's source file.

        Traces back through the source_file_id to find all versions and
        their associated diff log entries.

        Args:
            document_id: Any version's document UUID.

        Returns:
            List of history entry dicts ordered by version descending.
        """
        # First get the source_file_id for this document
        doc = await self.get_document(document_id)
        if doc is None:
            raise NotFoundError(f"Document {document_id} not found")

        source_file_id = doc.source_file_id

        # Get all versions for this source file
        versions_stmt = (
            select(ProcessedDocument)
            .where(ProcessedDocument.source_file_id == source_file_id)
            .order_by(ProcessedDocument.version.desc())
        )
        versions_result = await self.db.execute(versions_stmt)
        versions = versions_result.scalars().all()

        # Get all diff logs for this source file
        logs_stmt = (
            select(DiffLog)
            .where(DiffLog.source_file_id == source_file_id)
            .order_by(DiffLog.created_at.desc())
        )
        logs_result = await self.db.execute(logs_stmt)
        diff_logs = logs_result.scalars().all()

        # Index diff logs by document_id for quick lookup
        logs_by_doc: dict[uuid.UUID | None, DiffLog] = {}
        for log in diff_logs:
            logs_by_doc[log.document_id] = log

        history: list[dict[str, Any]] = []
        for version in versions:
            log = logs_by_doc.get(version.id)
            history.append({
                "document_id": version.id,
                "version": version.version,
                "is_current": version.is_current,
                "title": version.title,
                "summary": version.summary,
                "created_at": version.created_at,
                "edited_by": log.created_by if log else None,
                "justification": log.justification if log else None,
                "diff_type": log.diff_type if log else None,
            })

        return history

    # ── Citations ─────────────────────────────────────────────────────────

    async def get_citations(
        self, document_id: uuid.UUID
    ) -> list[Citation]:
        """Get all citations for a document with download URLs.

        Args:
            document_id: The document UUID.

        Returns:
            List of Citation model instances.

        Raises:
            NotFoundError: If the document does not exist.
        """
        doc = await self.get_document(document_id)
        if doc is None:
            raise NotFoundError(f"Document {document_id} not found")

        stmt = (
            select(Citation)
            .where(Citation.document_id == document_id)
            .order_by(Citation.citation_index)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ── Statistics ────────────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate collection statistics.

        Returns:
            Dict with total_documents, by_category, by_month,
            total_chunks, total_citations.
        """
        # Total current documents
        total_stmt = select(func.count()).where(
            ProcessedDocument.is_current.is_(True)
        ).select_from(ProcessedDocument)
        total_result = await self.db.execute(total_stmt)
        total_documents = total_result.scalar() or 0

        # By category
        cat_stmt = (
            select(
                ProcessedDocument.category,
                func.count().label("count"),
            )
            .where(ProcessedDocument.is_current.is_(True))
            .group_by(ProcessedDocument.category)
        )
        cat_result = await self.db.execute(cat_stmt)
        by_category = {row.category: row.count for row in cat_result}

        # By month (last 12 months)
        month_stmt = (
            select(
                func.date_trunc("month", ProcessedDocument.created_at).label("month"),
                func.count().label("count"),
            )
            .where(ProcessedDocument.is_current.is_(True))
            .group_by(text("1"))
            .order_by(text("1"))
            .limit(12)
        )
        month_result = await self.db.execute(month_stmt)
        by_month = [
            {"month": row.month.isoformat() if row.month else None, "count": row.count}
            for row in month_result
        ]

        # Total chunks
        chunks_stmt = select(func.count()).select_from(DocumentChunk)
        chunks_result = await self.db.execute(chunks_stmt)
        total_chunks = chunks_result.scalar() or 0

        # Total citations
        citations_stmt = select(func.count()).select_from(Citation)
        citations_result = await self.db.execute(citations_stmt)
        total_citations = citations_result.scalar() or 0

        return {
            "total_documents": total_documents,
            "by_category": by_category,
            "by_month": by_month,
            "total_chunks": total_chunks,
            "total_citations": total_citations,
        }

    # ── Categories ────────────────────────────────────────────────────────

    async def get_categories(self) -> list[dict[str, Any]]:
        """Get all categories with document counts.

        Returns:
            List of dicts with category and count keys.
        """
        stmt = (
            select(
                ProcessedDocument.category,
                func.count().label("count"),
            )
            .where(ProcessedDocument.is_current.is_(True))
            .group_by(ProcessedDocument.category)
            .order_by(func.count().desc())
        )
        result = await self.db.execute(stmt)
        return [{"category": row.category, "count": row.count} for row in result]

    # ── Entities (JSONB-based) ────────────────────────────────────────────

    async def get_entities(self) -> list[dict[str, Any]]:
        """Get all unique entities with mention counts from JSONB.

        Extracts entities from the JSONB ``entities`` column across all
        current documents. This is the relational fallback; the graph
        service provides richer entity queries.

        Returns:
            List of dicts with name, entity_type, and mention_count.
        """
        # Use jsonb_array_elements to unpack the entities array
        stmt = text("""
            SELECT
                entity->>'name' AS name,
                entity->>'type' AS entity_type,
                COUNT(*) AS mention_count
            FROM processed_documents,
                 jsonb_array_elements(entities) AS entity
            WHERE is_current = TRUE
              AND jsonb_typeof(entities) = 'array'
            GROUP BY entity->>'name', entity->>'type'
            ORDER BY mention_count DESC
        """)
        result = await self.db.execute(stmt)
        rows = result.mappings().all()

        return [
            {
                "name": row["name"],
                "entity_type": row["entity_type"],
                "mention_count": row["mention_count"],
            }
            for row in rows
        ]

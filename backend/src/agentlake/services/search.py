"""Search engine service — keyword, semantic, and hybrid search with RRF.

This service implements Layer 3 of the AgentLake architecture: full-text
keyword search via PostgreSQL tsvector, semantic search via pgvector
cosine distance, and hybrid search combining both with Reciprocal Rank
Fusion (RRF).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.core.exceptions import LLMGatewayError
from agentlake.models.document import ProcessedDocument
from agentlake.services.llm_client import LLMClient

logger = structlog.get_logger(__name__)


class SearchService:
    """Hybrid search engine combining keyword and semantic search.

    Args:
        db: Async SQLAlchemy session.
        llm_client: LLM gateway client for generating query embeddings.
    """

    def __init__(self, db: AsyncSession, llm_client: LLMClient) -> None:
        self.db = db
        self.llm_client = llm_client

    # ── Keyword Search ────────────────────────────────────────────────────

    async def keyword_search(
        self,
        query: str,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search using PostgreSQL tsvector with ts_rank_cd.

        Args:
            query: The search query string.
            limit: Maximum number of results to return.
            filters: Optional filter conditions (category, tags, date_from,
                date_to, entities, source_file_id).

        Returns:
            List of result dicts with id, title, summary, category, score,
            snippet, source_file_id, version, entities, created_at.
        """
        if not query.strip():
            return await self._recent_documents(limit, filters)

        ts_query = func.websearch_to_tsquery("english", query)

        rank_expr = func.ts_rank_cd(
            ProcessedDocument.search_vector,
            ts_query,
        )
        headline_expr = func.ts_headline(
            "english",
            ProcessedDocument.body_markdown,
            ts_query,
            "StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20, MaxFragments=2",
        )

        stmt = (
            select(
                ProcessedDocument.id,
                ProcessedDocument.title,
                ProcessedDocument.summary,
                ProcessedDocument.category,
                rank_expr.label("score"),
                headline_expr.label("snippet"),
                ProcessedDocument.source_file_id,
                ProcessedDocument.version,
                ProcessedDocument.entities,
                ProcessedDocument.created_at,
            )
            .where(
                and_(
                    ProcessedDocument.is_current.is_(True),
                    ProcessedDocument.search_vector.op("@@")(ts_query),
                )
            )
        )

        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(rank_expr.desc()).limit(limit)

        result = await self.db.execute(stmt)
        rows = result.mappings().all()

        logger.info(
            "keyword_search_completed",
            query=query,
            results=len(rows),
        )

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "category": row["category"],
                "score": float(row["score"]),
                "snippet": row["snippet"],
                "source_file_id": row["source_file_id"],
                "version": row["version"],
                "entities": row["entities"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ── Semantic Search ───────────────────────────────────────────────────

    async def semantic_search(
        self,
        query: str,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search using pgvector cosine distance.

        Args:
            query: The search query string.
            limit: Maximum number of results to return.
            filters: Optional filter conditions.

        Returns:
            List of result dicts with id, title, summary, category, score
            (cosine similarity), source_file_id, version, entities, created_at.
        """
        if not query.strip():
            return await self._recent_documents(limit, filters)

        try:
            embeddings = await self.llm_client.embed([query])
        except LLMGatewayError:
            logger.warning(
                "semantic_search_embedding_failed",
                query=query,
            )
            return []

        query_embedding = embeddings[0]

        # Cosine similarity = 1 - cosine distance
        cosine_distance = ProcessedDocument.embedding.cosine_distance(query_embedding)
        similarity_expr = (1 - cosine_distance).label("score")

        stmt = (
            select(
                ProcessedDocument.id,
                ProcessedDocument.title,
                ProcessedDocument.summary,
                ProcessedDocument.category,
                similarity_expr,
                ProcessedDocument.source_file_id,
                ProcessedDocument.version,
                ProcessedDocument.entities,
                ProcessedDocument.created_at,
            )
            .where(
                and_(
                    ProcessedDocument.is_current.is_(True),
                    ProcessedDocument.embedding.isnot(None),
                )
            )
        )

        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(cosine_distance).limit(limit)

        result = await self.db.execute(stmt)
        rows = result.mappings().all()

        logger.info(
            "semantic_search_completed",
            query=query,
            results=len(rows),
        )

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "category": row["category"],
                "score": float(row["score"]),
                "snippet": None,
                "source_file_id": row["source_file_id"],
                "version": row["version"],
                "entities": row["entities"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ── Hybrid Search ─────────────────────────────────────────────────────

    async def hybrid_search(
        self,
        query: str,
        limit: int = 20,
        keyword_weight: float = 0.4,
        semantic_weight: float = 0.6,
        filters: dict[str, Any] | None = None,
        k: int = 60,
    ) -> dict[str, Any]:
        """Hybrid search combining keyword and semantic results with RRF.

        Reciprocal Rank Fusion merges two ranked lists by assigning each
        result a score of ``weight / (k + rank)`` from each list, then
        summing the scores and re-sorting.

        Args:
            query: The search query string.
            limit: Maximum number of results to return.
            keyword_weight: Weight for keyword search in RRF.
            semantic_weight: Weight for semantic search in RRF.
            filters: Optional filter conditions.
            k: RRF smoothing constant (default 60).

        Returns:
            Dict with results, total, search_time_ms, query, mode.
        """
        start_time = time.monotonic()

        if not query.strip():
            recent = await self._recent_documents(limit, filters)
            elapsed = (time.monotonic() - start_time) * 1000
            return {
                "results": recent,
                "total": len(recent),
                "search_time_ms": round(elapsed, 2),
                "query": query,
                "mode": "hybrid",
            }

        # Run both searches in parallel with a wider fetch window
        wider_limit = min(limit * 3, 100)

        keyword_task = asyncio.create_task(
            self.keyword_search(query, limit=wider_limit, filters=filters)
        )
        semantic_task = asyncio.create_task(
            self.semantic_search(query, limit=wider_limit, filters=filters)
        )

        keyword_results, semantic_results = await asyncio.gather(
            keyword_task, semantic_task, return_exceptions=True
        )

        # Handle partial failures gracefully
        if isinstance(keyword_results, BaseException):
            logger.warning(
                "hybrid_keyword_search_failed",
                error=str(keyword_results),
            )
            keyword_results = []
        if isinstance(semantic_results, BaseException):
            logger.warning(
                "hybrid_semantic_search_failed",
                error=str(semantic_results),
            )
            semantic_results = []

        # Build RRF scores
        rrf_scores: dict[uuid.UUID, float] = {}
        result_map: dict[uuid.UUID, dict[str, Any]] = {}

        for rank, hit in enumerate(keyword_results, start=1):
            doc_id = hit["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + keyword_weight / (k + rank)
            if doc_id not in result_map:
                result_map[doc_id] = hit

        for rank, hit in enumerate(semantic_results, start=1):
            doc_id = hit["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + semantic_weight / (k + rank)
            if doc_id not in result_map:
                result_map[doc_id] = hit
            elif hit.get("snippet") is None and result_map[doc_id].get("snippet"):
                # Keep the keyword snippet if semantic doesn't have one
                pass
            elif hit.get("snippet"):
                result_map[doc_id]["snippet"] = hit["snippet"]

        # Sort by RRF score and take top results
        sorted_ids = sorted(rrf_scores, key=lambda doc_id: rrf_scores[doc_id], reverse=True)
        top_ids = sorted_ids[:limit]

        merged = []
        for doc_id in top_ids:
            hit = result_map[doc_id].copy()
            hit["score"] = round(rrf_scores[doc_id], 6)
            merged.append(hit)

        elapsed = (time.monotonic() - start_time) * 1000

        logger.info(
            "hybrid_search_completed",
            query=query,
            keyword_count=len(keyword_results),
            semantic_count=len(semantic_results),
            merged_count=len(merged),
            search_time_ms=round(elapsed, 2),
        )

        return {
            "results": merged,
            "total": len(merged),
            "search_time_ms": round(elapsed, 2),
            "query": query,
            "mode": "hybrid",
        }

    # ── Filter Builder ────────────────────────────────────────────────────

    def _apply_filters(self, stmt: Any, filters: dict[str, Any] | None) -> Any:
        """Apply filter conditions to a SQLAlchemy select statement.

        Args:
            stmt: The select statement to augment.
            filters: Dict of filter keys/values. Supported keys:
                category, tags, date_from, date_to, entities, source_file_id.

        Returns:
            The augmented statement with WHERE clauses added.
        """
        if not filters:
            return stmt

        if filters.get("category"):
            stmt = stmt.where(ProcessedDocument.category == filters["category"])

        if filters.get("date_from"):
            stmt = stmt.where(ProcessedDocument.created_at >= filters["date_from"])

        if filters.get("date_to"):
            stmt = stmt.where(ProcessedDocument.created_at <= filters["date_to"])

        if filters.get("source_file_id"):
            stmt = stmt.where(
                ProcessedDocument.source_file_id == filters["source_file_id"]
            )

        if filters.get("entities"):
            # JSONB containment: entities column must contain at least one of
            # the requested entity names.  The entities column stores a JSON
            # array of objects like [{"name": "Siemens", "type": "ORG"}, ...].
            for entity_name in filters["entities"]:
                stmt = stmt.where(
                    ProcessedDocument.entities.op("@>")(
                        func.cast(
                            f'[{{"name": "{entity_name}"}}]',
                            type_=ProcessedDocument.entities.type,
                        )
                    )
                )

        if filters.get("tags"):
            # Tags are on the File model via a join table.  Use a subquery
            # to find source_file_ids that have the requested tags.
            from agentlake.models.tag import FileTag, Tag

            tag_subq = (
                select(FileTag.file_id)
                .join(Tag, Tag.id == FileTag.tag_id)
                .where(Tag.name.in_(filters["tags"]))
                .distinct()
                .scalar_subquery()
            )
            stmt = stmt.where(ProcessedDocument.source_file_id.in_(tag_subq))

        return stmt

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _recent_documents(
        self,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent current documents when no query is provided.

        Args:
            limit: Maximum number of results.
            filters: Optional filter conditions.

        Returns:
            List of result dicts ordered by created_at descending.
        """
        stmt = (
            select(
                ProcessedDocument.id,
                ProcessedDocument.title,
                ProcessedDocument.summary,
                ProcessedDocument.category,
                ProcessedDocument.source_file_id,
                ProcessedDocument.version,
                ProcessedDocument.entities,
                ProcessedDocument.created_at,
            )
            .where(ProcessedDocument.is_current.is_(True))
        )

        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(ProcessedDocument.created_at.desc()).limit(limit)

        result = await self.db.execute(stmt)
        rows = result.mappings().all()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "category": row["category"],
                "score": 0.0,
                "snippet": None,
                "source_file_id": row["source_file_id"],
                "version": row["version"],
                "entities": row["entities"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

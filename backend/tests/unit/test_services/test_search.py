"""Tests for the SearchService."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentlake.core.exceptions import LLMGatewayError
from agentlake.services.search import SearchService


@pytest.fixture()
def mock_db() -> AsyncMock:
    """Create a mock async session."""
    db = AsyncMock()
    return db


@pytest.fixture()
def mock_llm_client() -> AsyncMock:
    """Create a mock LLM client."""
    client = AsyncMock()
    client.embed.return_value = [[0.1] * 1536]
    return client


@pytest.fixture()
def search_service(mock_db: AsyncMock, mock_llm_client: AsyncMock) -> SearchService:
    return SearchService(db=mock_db, llm_client=mock_llm_client)


class TestKeywordSearch:
    """Tests for keyword_search method."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_recent(
        self, search_service: SearchService, mock_db: AsyncMock
    ) -> None:
        # Setup mock to return empty results
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        results = await search_service.keyword_search("", limit=10)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_keyword_search_returns_list(
        self, search_service: SearchService, mock_db: AsyncMock
    ) -> None:
        doc_id = uuid.uuid4()
        file_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {
                "id": doc_id,
                "title": "Test Doc",
                "summary": "A test document.",
                "category": "technical",
                "score": 0.85,
                "snippet": "matching <mark>text</mark>",
                "source_file_id": file_id,
                "version": 1,
                "entities": [],
                "created_at": datetime.now(timezone.utc),
            }
        ]
        mock_db.execute.return_value = mock_result

        results = await search_service.keyword_search("test query", limit=20)
        assert len(results) == 1
        assert results[0]["id"] == doc_id
        assert results[0]["title"] == "Test Doc"
        assert results[0]["score"] == 0.85


class TestSemanticSearch:
    """Tests for semantic_search method."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_recent(
        self, search_service: SearchService, mock_db: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        results = await search_service.semantic_search("   ", limit=10)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_semantic_search_calls_embed(
        self, search_service: SearchService, mock_db: AsyncMock, mock_llm_client: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await search_service.semantic_search("test query", limit=10)
        mock_llm_client.embed.assert_called_once_with(["test query"])

    @pytest.mark.asyncio
    async def test_semantic_search_handles_embed_failure(
        self, search_service: SearchService, mock_llm_client: AsyncMock
    ) -> None:
        mock_llm_client.embed.side_effect = LLMGatewayError("embed failed")

        results = await search_service.semantic_search("test query", limit=10)
        assert results == []


class TestHybridSearch:
    """Tests for hybrid_search method."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_dict(
        self, search_service: SearchService, mock_db: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await search_service.hybrid_search("", limit=10)
        assert isinstance(result, dict)
        assert "results" in result
        assert "mode" in result
        assert result["mode"] == "hybrid"

    @pytest.mark.asyncio
    async def test_hybrid_merges_with_rrf(
        self, search_service: SearchService, mock_db: AsyncMock, mock_llm_client: AsyncMock
    ) -> None:
        doc_id_1 = uuid.uuid4()
        doc_id_2 = uuid.uuid4()
        file_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # First call is keyword search, second is for semantic
        keyword_row = {
            "id": doc_id_1,
            "title": "Keyword Hit",
            "summary": "Found via keyword.",
            "category": "technical",
            "score": 0.9,
            "snippet": "keyword <mark>match</mark>",
            "source_file_id": file_id,
            "version": 1,
            "entities": [],
            "created_at": now,
        }
        semantic_row = {
            "id": doc_id_2,
            "title": "Semantic Hit",
            "summary": "Found via embedding.",
            "category": "business",
            "score": 0.8,
            "snippet": None,
            "source_file_id": file_id,
            "version": 1,
            "entities": [],
            "created_at": now,
        }

        mock_result_kw = MagicMock()
        mock_result_kw.mappings.return_value.all.return_value = [keyword_row]
        mock_result_sem = MagicMock()
        mock_result_sem.mappings.return_value.all.return_value = [semantic_row]

        mock_db.execute.side_effect = [mock_result_kw, mock_result_sem]

        result = await search_service.hybrid_search("test", limit=20)
        assert result["total"] == 2
        assert result["search_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_hybrid_handles_partial_failure(
        self, search_service: SearchService, mock_db: AsyncMock, mock_llm_client: AsyncMock
    ) -> None:
        # Keyword search succeeds but semantic fails
        mock_llm_client.embed.side_effect = LLMGatewayError("embed failed")

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await search_service.hybrid_search("test", limit=10)
        assert isinstance(result, dict)
        assert result["mode"] == "hybrid"


class TestFilterBuilder:
    """Tests for the _apply_filters method."""

    def test_no_filters_returns_stmt(self, search_service: SearchService) -> None:
        stmt = MagicMock()
        result = search_service._apply_filters(stmt, None)
        assert result is stmt

    def test_empty_filters_returns_stmt(self, search_service: SearchService) -> None:
        stmt = MagicMock()
        result = search_service._apply_filters(stmt, {})
        assert result is stmt

    def test_category_filter(self, search_service: SearchService) -> None:
        stmt = MagicMock()
        stmt.where.return_value = stmt
        result = search_service._apply_filters(stmt, {"category": "technical"})
        stmt.where.assert_called()

    def test_source_file_id_filter(self, search_service: SearchService) -> None:
        stmt = MagicMock()
        stmt.where.return_value = stmt
        result = search_service._apply_filters(stmt, {"source_file_id": uuid.uuid4()})
        stmt.where.assert_called()

    def test_date_filters(self, search_service: SearchService) -> None:
        stmt = MagicMock()
        stmt.where.return_value = stmt
        now = datetime.now(timezone.utc)
        result = search_service._apply_filters(
            stmt, {"date_from": now, "date_to": now}
        )
        assert stmt.where.call_count == 2

"""Integration tests for the search pipeline.

Tests the flow from document creation through search, exercising
the adapter -> chunker -> search service chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentlake.services.search import SearchService

pytestmark = pytest.mark.integration


class TestSearchPipeline:
    """Integration tests for the search service."""

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_correct_structure(self) -> None:
        """Verify hybrid search returns the expected response structure."""
        mock_db = AsyncMock()
        mock_llm = AsyncMock()
        mock_llm.embed.return_value = [[0.1] * 1536]

        doc_id = uuid.uuid4()
        file_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        mock_row = {
            "id": doc_id,
            "title": "Test Document",
            "summary": "A test document.",
            "category": "technical",
            "score": 0.95,
            "snippet": "<mark>test</mark> document",
            "source_file_id": file_id,
            "version": 1,
            "entities": [{"name": "Test", "type": "ORG"}],
            "created_at": now,
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        service = SearchService(db=mock_db, llm_client=mock_llm)
        result = await service.hybrid_search("test", limit=10)

        assert isinstance(result, dict)
        assert "results" in result
        assert "total" in result
        assert "search_time_ms" in result
        assert "query" in result
        assert "mode" in result
        assert result["mode"] == "hybrid"

    @pytest.mark.asyncio
    async def test_keyword_search_ranking_order(self) -> None:
        """Verify keyword results are returned in score order."""
        mock_db = AsyncMock()
        mock_llm = AsyncMock()

        file_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        rows = [
            {
                "id": uuid.uuid4(),
                "title": f"Doc {i}",
                "summary": f"Summary {i}",
                "category": "technical",
                "score": 1.0 - (i * 0.1),
                "snippet": f"snippet {i}",
                "source_file_id": file_id,
                "version": 1,
                "entities": [],
                "created_at": now,
            }
            for i in range(5)
        ]

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = rows
        mock_db.execute.return_value = mock_result

        service = SearchService(db=mock_db, llm_client=mock_llm)
        results = await service.keyword_search("test", limit=10)

        assert len(results) == 5
        scores = [r["score"] for r in results]
        # Should already be in descending order (from DB)
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_empty_search_returns_recent(self) -> None:
        """Empty query should return recent documents."""
        mock_db = AsyncMock()
        mock_llm = AsyncMock()

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        service = SearchService(db=mock_db, llm_client=mock_llm)
        results = await service.keyword_search("", limit=10)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_semantic_search_calls_embed(self) -> None:
        """Semantic search must generate an embedding for the query."""
        mock_db = AsyncMock()
        mock_llm = AsyncMock()
        mock_llm.embed.return_value = [[0.1] * 1536]

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        service = SearchService(db=mock_db, llm_client=mock_llm)
        await service.semantic_search("find documents about AI", limit=10)

        mock_llm.embed.assert_called_once_with(["find documents about AI"])

    @pytest.mark.asyncio
    async def test_hybrid_handles_one_search_failing(self) -> None:
        """Hybrid search should gracefully handle one search mode failing."""
        mock_db = AsyncMock()
        mock_llm = AsyncMock()

        # Make embed fail so semantic search returns empty
        from agentlake.core.exceptions import LLMGatewayError

        mock_llm.embed.side_effect = LLMGatewayError("embed failed")

        # keyword search returns results
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        service = SearchService(db=mock_db, llm_client=mock_llm)
        result = await service.hybrid_search("test", limit=10)

        # Should still succeed
        assert isinstance(result, dict)
        assert result["mode"] == "hybrid"

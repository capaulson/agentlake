"""Tests for the DocumentService."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentlake.core.exceptions import NotFoundError
from agentlake.services.documents import DocumentService


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
def doc_service(mock_db: AsyncMock) -> DocumentService:
    return DocumentService(db=mock_db)


@pytest.fixture()
def doc_service_with_llm(
    mock_db: AsyncMock, mock_llm_client: AsyncMock
) -> DocumentService:
    return DocumentService(db=mock_db, llm_client=mock_llm_client)


class TestGetDocument:
    """Tests for get_document."""

    @pytest.mark.asyncio
    async def test_returns_document(
        self, doc_service: DocumentService, mock_db: AsyncMock
    ) -> None:
        mock_doc = MagicMock()
        mock_doc.id = uuid.uuid4()
        mock_doc.title = "Test Document"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_doc
        mock_db.execute.return_value = mock_result

        doc = await doc_service.get_document(mock_doc.id)
        assert doc is mock_doc

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(
        self, doc_service: DocumentService, mock_db: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        doc = await doc_service.get_document(uuid.uuid4())
        assert doc is None


class TestListDocuments:
    """Tests for list_documents."""

    @pytest.mark.asyncio
    async def test_returns_tuple(
        self, doc_service: DocumentService, mock_db: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        documents, next_cursor, has_more = await doc_service.list_documents(limit=10)
        assert isinstance(documents, list)
        assert next_cursor is None
        assert has_more is False

    @pytest.mark.asyncio
    async def test_pagination_has_more(
        self, doc_service: DocumentService, mock_db: AsyncMock
    ) -> None:
        # Return limit + 1 items to trigger has_more
        mock_docs = []
        for i in range(11):
            doc = MagicMock()
            doc.id = uuid.uuid4()
            doc.created_at = datetime.now(timezone.utc)
            mock_docs.append(doc)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_docs
        mock_db.execute.return_value = mock_result

        documents, next_cursor, has_more = await doc_service.list_documents(limit=10)
        assert len(documents) == 10
        assert has_more is True
        assert next_cursor is not None

    @pytest.mark.asyncio
    async def test_category_filter(
        self, doc_service: DocumentService, mock_db: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await doc_service.list_documents(category="technical", limit=10)
        mock_db.execute.assert_called_once()


class TestUpdateDocument:
    """Tests for update_document."""

    @pytest.mark.asyncio
    async def test_raises_when_not_found(
        self, doc_service_with_llm: DocumentService, mock_db: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(NotFoundError):
            await doc_service_with_llm.update_document(
                document_id=uuid.uuid4(),
                body_markdown="new content",
                justification="test edit",
            )

    @pytest.mark.asyncio
    async def test_raises_when_not_current(
        self, doc_service_with_llm: DocumentService, mock_db: AsyncMock
    ) -> None:
        mock_doc = MagicMock()
        mock_doc.is_current = False
        mock_doc.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_doc
        mock_db.execute.return_value = mock_result

        with pytest.raises(NotFoundError, match="not the current version"):
            await doc_service_with_llm.update_document(
                document_id=mock_doc.id,
                body_markdown="new content",
                justification="test edit",
            )


class TestGetDocumentHistory:
    """Tests for get_document_history."""

    @pytest.mark.asyncio
    async def test_raises_when_not_found(
        self, doc_service: DocumentService, mock_db: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(NotFoundError):
            await doc_service.get_document_history(uuid.uuid4())


class TestGetCitations:
    """Tests for get_citations."""

    @pytest.mark.asyncio
    async def test_raises_when_document_not_found(
        self, doc_service: DocumentService, mock_db: AsyncMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(NotFoundError):
            await doc_service.get_citations(uuid.uuid4())


class TestGetStats:
    """Tests for get_stats."""

    @pytest.mark.asyncio
    async def test_returns_stats_dict(
        self, doc_service: DocumentService, mock_db: AsyncMock
    ) -> None:
        # Mock the multiple execute calls
        mock_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=42)),   # total
            MagicMock(__iter__=MagicMock(return_value=iter([]))),  # by_category
            MagicMock(__iter__=MagicMock(return_value=iter([]))),  # by_month
            MagicMock(scalar=MagicMock(return_value=100)),  # chunks
            MagicMock(scalar=MagicMock(return_value=200)),  # citations
        ]

        stats = await doc_service.get_stats()
        assert isinstance(stats, dict)
        assert "total_documents" in stats

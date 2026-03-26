"""Tests for the query API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.config import Settings
from agentlake.core.auth import hash_api_key
from agentlake.models.api_key import ApiKey


@pytest.fixture()
def _settings() -> Settings:
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        DATABASE_SYNC_URL="sqlite:///:memory:",
        DATABASE_POOL_SIZE=5,
        DATABASE_MAX_OVERFLOW=0,
        REDIS_URL="redis://localhost:6379/15",
        MINIO_ENDPOINT="localhost:9000",
        MINIO_ACCESS_KEY="test",
        MINIO_SECRET_KEY="test_secret",
        MINIO_BUCKET="test-bucket",
        MINIO_SECURE=False,
        LLM_GATEWAY_URL="http://localhost:8001",
        LLM_GATEWAY_SERVICE_TOKEN="test-token",
        JWT_SECRET="test-jwt-secret",
        API_KEY_SALT="test-salt",
        DEFAULT_ADMIN_API_KEY="test-admin-key",
        LOG_LEVEL="DEBUG",
        LOG_FORMAT="console",
    )


def _make_api_key(role: str = "admin", salt: str = "test-salt") -> tuple[str, ApiKey]:
    raw_key = f"test-key-{uuid.uuid4().hex[:8]}"
    key_hash = hash_api_key(raw_key, salt)
    api_key = ApiKey(
        id=uuid.uuid4(),
        name="test-user",
        key_hash=key_hash,
        role=role,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return raw_key, api_key


@pytest.fixture()
def _app_and_client(_settings: Settings):
    from agentlake.main import create_app
    from agentlake.core.database import get_db

    app = create_app()
    mock_session = AsyncMock(spec=AsyncSession)
    raw_key, api_key_obj = _make_api_key("admin", _settings.API_KEY_SALT)

    mock_auth_result = MagicMock()
    mock_auth_result.scalar_one_or_none.return_value = api_key_obj
    mock_session.execute.return_value = mock_auth_result
    mock_session.flush = AsyncMock()

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db
    return app, mock_session, raw_key


class TestSearchEndpoint:
    """Tests for GET /api/v1/query/search."""

    @pytest.mark.asyncio
    async def test_search_requires_auth(self, _settings: Settings) -> None:
        from agentlake.main import create_app
        from agentlake.core.database import get_db

        app = create_app()
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db] = _override_db

        with patch("agentlake.core.auth.get_settings", return_value=_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/query/search")

        assert resp.status_code == 403


class TestListDocumentsEndpoint:
    """Tests for GET /api/v1/query/documents."""

    @pytest.mark.asyncio
    async def test_list_documents_with_auth(
        self, _app_and_client, _settings: Settings
    ) -> None:
        app, mock_session, raw_key = _app_and_client

        # Mock listing result
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []
        mock_session.execute.side_effect = [
            mock_session.execute.return_value,  # auth
            mock_list_result,  # list documents
        ]

        with (
            patch("agentlake.core.auth.get_settings", return_value=_settings),
            patch("agentlake.api.query.get_settings", return_value=_settings),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/query/documents",
                    headers={"X-API-Key": raw_key},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body


class TestGetDocumentEndpoint:
    """Tests for GET /api/v1/query/documents/{id}."""

    @pytest.mark.asyncio
    async def test_get_document_not_found(
        self, _app_and_client, _settings: Settings
    ) -> None:
        app, mock_session, raw_key = _app_and_client

        mock_not_found = MagicMock()
        mock_not_found.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [
            mock_session.execute.return_value,  # auth
            mock_not_found,  # doc lookup
        ]

        with (
            patch("agentlake.core.auth.get_settings", return_value=_settings),
            patch("agentlake.api.query.get_settings", return_value=_settings),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/query/documents/{uuid.uuid4()}",
                    headers={"X-API-Key": raw_key},
                )

        assert resp.status_code == 404


class TestUpdateDocumentEndpoint:
    """Tests for PUT /api/v1/query/documents/{id}."""

    @pytest.mark.asyncio
    async def test_update_requires_editor_role(self, _settings: Settings) -> None:
        from agentlake.main import create_app
        from agentlake.core.database import get_db

        app = create_app()
        mock_session = AsyncMock(spec=AsyncSession)

        # Create a viewer key (insufficient role)
        raw_key, api_key_obj = _make_api_key("viewer", _settings.API_KEY_SALT)
        mock_auth_result = MagicMock()
        mock_auth_result.scalar_one_or_none.return_value = api_key_obj
        mock_session.execute.return_value = mock_auth_result

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db] = _override_db

        with (
            patch("agentlake.core.auth.get_settings", return_value=_settings),
            patch("agentlake.api.query.get_settings", return_value=_settings),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.put(
                    f"/api/v1/query/documents/{uuid.uuid4()}",
                    json={
                        "body_markdown": "new content",
                        "justification": "test edit",
                    },
                    headers={"X-API-Key": raw_key},
                )

        # Viewer should not be able to edit
        assert resp.status_code == 403

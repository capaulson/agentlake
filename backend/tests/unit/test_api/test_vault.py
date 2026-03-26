"""Tests for the vault API endpoints."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.config import Settings
from agentlake.core.auth import hash_api_key
from agentlake.models.api_key import ApiKey
from agentlake.models.file import File, FileStatus


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
    """Create a raw key and matching ApiKey model."""
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
    """Create FastAPI app with overridden dependencies."""
    from agentlake.main import create_app
    from agentlake.core.database import get_db

    app = create_app()

    mock_session = AsyncMock(spec=AsyncSession)
    raw_key, api_key_obj = _make_api_key("admin", _settings.API_KEY_SALT)

    # Mock DB query for API key auth
    mock_auth_result = MagicMock()
    mock_auth_result.scalar_one_or_none.return_value = api_key_obj

    # Default: return auth result for any query
    mock_session.execute.return_value = mock_auth_result
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db

    return app, mock_session, raw_key, api_key_obj


class TestVaultListFiles:
    """Tests for GET /api/v1/vault/files."""

    @pytest.mark.asyncio
    async def test_list_files_no_auth_returns_error(self, _settings: Settings) -> None:
        from agentlake.main import create_app
        from agentlake.core.database import get_db

        app = create_app()

        mock_session = AsyncMock(spec=AsyncSession)
        # No API key found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db] = _override_db

        with patch("agentlake.core.auth.get_settings", return_value=_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/vault/files")

        # Should fail auth (403)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_files_with_auth(
        self, _app_and_client, _settings: Settings
    ) -> None:
        app, mock_session, raw_key, _ = _app_and_client

        # Mock second execute call for actual file listing
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.unique.return_value.all.return_value = []
        mock_session.execute.side_effect = [
            mock_session.execute.return_value,  # auth query
            mock_list_result,  # file listing query
        ]

        with patch("agentlake.core.auth.get_settings", return_value=_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/vault/files",
                    headers={"X-API-Key": raw_key},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)


class TestVaultGetFile:
    """Tests for GET /api/v1/vault/files/{file_id}."""

    @pytest.mark.asyncio
    async def test_get_file_not_found(
        self, _app_and_client, _settings: Settings
    ) -> None:
        app, mock_session, raw_key, _ = _app_and_client

        # First call: auth, second call: file lookup returns None
        mock_not_found = MagicMock()
        mock_not_found.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [
            mock_session.execute.return_value,  # auth
            mock_not_found,  # file lookup
        ]

        with patch("agentlake.core.auth.get_settings", return_value=_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/vault/files/{uuid.uuid4()}",
                    headers={"X-API-Key": raw_key},
                )

        assert resp.status_code == 404


class TestVaultDeleteFile:
    """Tests for DELETE /api/v1/vault/files/{file_id}."""

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self, _app_and_client, _settings: Settings
    ) -> None:
        app, mock_session, raw_key, _ = _app_and_client

        mock_not_found = MagicMock()
        mock_not_found.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [
            mock_session.execute.return_value,  # auth
            mock_not_found,  # file lookup
        ]

        with patch("agentlake.core.auth.get_settings", return_value=_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    f"/api/v1/vault/files/{uuid.uuid4()}",
                    headers={"X-API-Key": raw_key},
                )

        assert resp.status_code == 404


class TestVaultUpload:
    """Tests for POST /api/v1/vault/upload."""

    @pytest.mark.asyncio
    async def test_upload_empty_file_returns_422(
        self, _app_and_client, _settings: Settings
    ) -> None:
        app, mock_session, raw_key, _ = _app_and_client

        with patch("agentlake.core.auth.get_settings", return_value=_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/vault/upload",
                    files={"request": ("empty.txt", b"", "text/plain")},
                    headers={"X-API-Key": raw_key},
                )

        # Empty file should be rejected with a validation error
        assert resp.status_code == 422


class TestVaultAuth:
    """Tests for auth behavior on vault endpoints."""

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_403(self, _settings: Settings) -> None:
        from agentlake.main import create_app
        from agentlake.core.database import get_db

        app = create_app()
        mock_session = AsyncMock(spec=AsyncSession)

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db] = _override_db

        with patch("agentlake.core.auth.get_settings", return_value=_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/vault/files")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_403(self, _settings: Settings) -> None:
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
                resp = await client.get(
                    "/api/v1/vault/files",
                    headers={"X-API-Key": "definitely-not-valid"},
                )

        assert resp.status_code == 403

"""Tests for the health check endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.config import Settings


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


class TestHealthEndpoint:
    """Tests for GET /api/v1/health."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, _settings: Settings) -> None:
        from agentlake.main import create_app
        from agentlake.core.database import get_db

        app = create_app()

        # Override DB to return a mock session
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_session.execute.return_value = mock_result

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db] = _override_db

        # Patch Redis and MinIO checks to avoid real connections
        with (
            patch("agentlake.api.health.get_settings", return_value=_settings),
            patch("redis.asyncio.from_url") as mock_redis_factory,
            patch("agentlake.services.storage.Minio") as mock_minio_cls,
        ):
            mock_redis_conn = AsyncMock()
            mock_redis_conn.ping.return_value = True
            mock_redis_factory.return_value = mock_redis_conn

            mock_minio = MagicMock()
            mock_minio.bucket_exists.return_value = True
            mock_minio_cls.return_value = mock_minio

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/health")

            assert resp.status_code == 200
            body = resp.json()
            assert "data" in body
            assert "meta" in body
            assert body["data"]["status"] in ("healthy", "degraded")
            assert "components" in body["data"]
            assert "version" in body["data"]

    @pytest.mark.asyncio
    async def test_health_response_envelope(self, _settings: Settings) -> None:
        from agentlake.main import create_app
        from agentlake.core.database import get_db

        app = create_app()

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value = MagicMock()

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db] = _override_db

        with (
            patch("agentlake.api.health.get_settings", return_value=_settings),
            patch("redis.asyncio.from_url") as mock_redis_factory,
            patch("agentlake.services.storage.Minio") as mock_minio_cls,
        ):
            mock_redis_conn = AsyncMock()
            mock_redis_conn.ping.return_value = True
            mock_redis_factory.return_value = mock_redis_conn

            mock_minio = MagicMock()
            mock_minio.bucket_exists.return_value = True
            mock_minio_cls.return_value = mock_minio

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/health")

            body = resp.json()
            assert "meta" in body
            assert "request_id" in body["meta"]
            assert "timestamp" in body["meta"]

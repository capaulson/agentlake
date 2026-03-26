"""Tests for the StorageService with mocked MinIO."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from agentlake.config import Settings
from agentlake.services.storage import StorageService


@pytest.fixture()
def settings() -> Settings:
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


@pytest.fixture()
def mock_minio_client() -> MagicMock:
    """A MagicMock standing in for the MinIO client."""
    client = MagicMock()
    client.bucket_exists.return_value = True
    client.put_object.return_value = None
    client.get_object.return_value = MagicMock(
        read=MagicMock(return_value=b"fake file content"),
        close=MagicMock(),
        release_conn=MagicMock(),
    )
    client.stat_object.return_value = MagicMock(
        size=1024,
        content_type="application/octet-stream",
        etag="abc123",
    )
    client.remove_object.return_value = None
    client.presigned_get_object.return_value = "http://localhost:9000/test-bucket/file.pdf"
    client.make_bucket.return_value = None
    return client


class TestStorageService:
    """Unit tests for StorageService with mocked MinIO client."""

    @pytest.mark.asyncio
    async def test_upload_file(
        self, settings: Settings, mock_minio_client: MagicMock
    ) -> None:
        with patch("agentlake.services.storage.Minio", return_value=mock_minio_client):
            svc = StorageService(settings)

        data = io.BytesIO(b"file content here")
        key = await svc.upload_file(
            storage_key="abc/test.txt",
            data=data,
            size=17,
            content_type="text/plain",
        )
        assert key == "abc/test.txt"
        mock_minio_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_file(
        self, settings: Settings, mock_minio_client: MagicMock
    ) -> None:
        with patch("agentlake.services.storage.Minio", return_value=mock_minio_client):
            svc = StorageService(settings)

        content = await svc.download_file("abc/test.txt")
        assert content == b"fake file content"
        mock_minio_client.get_object.assert_called_once_with("test-bucket", "abc/test.txt")

    @pytest.mark.asyncio
    async def test_delete_file(
        self, settings: Settings, mock_minio_client: MagicMock
    ) -> None:
        with patch("agentlake.services.storage.Minio", return_value=mock_minio_client):
            svc = StorageService(settings)

        await svc.delete_file("abc/test.txt")
        mock_minio_client.remove_object.assert_called_once_with("test-bucket", "abc/test.txt")

    @pytest.mark.asyncio
    async def test_ensure_bucket_creates_when_missing(
        self, settings: Settings, mock_minio_client: MagicMock
    ) -> None:
        mock_minio_client.bucket_exists.return_value = False
        with patch("agentlake.services.storage.Minio", return_value=mock_minio_client):
            svc = StorageService(settings)

        await svc.ensure_bucket()
        mock_minio_client.make_bucket.assert_called_once_with("test-bucket")

    @pytest.mark.asyncio
    async def test_ensure_bucket_skips_when_exists(
        self, settings: Settings, mock_minio_client: MagicMock
    ) -> None:
        mock_minio_client.bucket_exists.return_value = True
        with patch("agentlake.services.storage.Minio", return_value=mock_minio_client):
            svc = StorageService(settings)

        await svc.ensure_bucket()
        mock_minio_client.make_bucket.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_presigned_url(
        self, settings: Settings, mock_minio_client: MagicMock
    ) -> None:
        with patch("agentlake.services.storage.Minio", return_value=mock_minio_client):
            svc = StorageService(settings)

        url = await svc.get_presigned_url("abc/test.txt")
        assert "localhost:9000" in url
        mock_minio_client.presigned_get_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_returns_storage_key(
        self, settings: Settings, mock_minio_client: MagicMock
    ) -> None:
        with patch("agentlake.services.storage.Minio", return_value=mock_minio_client):
            svc = StorageService(settings)

        key = await svc.upload_file(
            storage_key="custom/path/file.pdf",
            data=io.BytesIO(b"pdf content"),
            size=11,
            content_type="application/pdf",
        )
        assert key == "custom/path/file.pdf"

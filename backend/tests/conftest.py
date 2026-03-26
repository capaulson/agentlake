"""Shared pytest fixtures for the AgentLake backend test suite."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agentlake.config import Settings
from agentlake.core.database import get_db
from agentlake.models.base import Base


# ── Test Settings ────────────────────────────────────────────────────────────


@pytest.fixture()
def settings() -> Settings:
    """Return a Settings instance with safe test defaults.

    Uses an in-memory SQLite database via aiosqlite so tests never touch
    the real PostgreSQL instance.  Override individual fields in your
    test if needed.
    """
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


# ── Async Database Session ───────────────────────────────────────────────────


@pytest.fixture()
async def async_session(settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh async session backed by an in-memory SQLite DB.

    Creates all tables before the test and drops them afterwards.
    """
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ── HTTP Test Client ─────────────────────────────────────────────────────────


@pytest.fixture()
async def client(
    settings: Settings, async_session: AsyncSession
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient wired to the FastAPI test app.

    The database dependency is overridden to use the test session
    so no real PostgreSQL connection is needed.
    """
    from agentlake.main import create_app

    application = create_app()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    application.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Mock MinIO ───────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_minio() -> MagicMock:
    """Return a MagicMock standing in for the MinIO client.

    Pre-configures commonly called methods with sensible return values.
    """
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
    return client


# ── Mock Redis ───────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_redis() -> AsyncMock:
    """Return an AsyncMock standing in for the async Redis client.

    Pre-configures common operations (get, set, delete, publish).
    """
    client = AsyncMock()
    client.get.return_value = None
    client.set.return_value = True
    client.delete.return_value = 1
    client.publish.return_value = 1
    client.expire.return_value = True
    client.exists.return_value = 0
    client.incr.return_value = 1
    client.pipeline.return_value = AsyncMock(
        execute=AsyncMock(return_value=[True, True]),
        __aenter__=AsyncMock(),
        __aexit__=AsyncMock(),
    )
    return client


# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def random_uuid() -> uuid.UUID:
    """Return a random UUID for test data."""
    return uuid.uuid4()

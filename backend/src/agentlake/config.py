"""Application configuration via environment variables."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment variables.

    All values have sensible development defaults so the app can start
    locally without an .env file.  Production deploys MUST override
    secrets (JWT_SECRET, API keys, passwords).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://agentlake:agentlake_dev@localhost:5432/agentlake"
    )
    DATABASE_SYNC_URL: str = (
        "postgresql://agentlake:agentlake_dev@localhost:5432/agentlake"
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── MinIO / S3 ───────────────────────────────────────────────────────
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "agentlake"
    MINIO_SECRET_KEY: str = "agentlake_dev_secret"
    MINIO_BUCKET: str = "agentlake-vault"
    MINIO_SECURE: bool = False

    # ── LLM Gateway ─────────────────────────────────────────────────────
    LLM_GATEWAY_URL: str = "http://localhost:8001"
    LLM_GATEWAY_SERVICE_TOKEN: str = ""

    # ── API Server ───────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Authentication ───────────────────────────────────────────────────
    JWT_SECRET: str = "CHANGE-ME-IN-PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    API_KEY_SALT: str = "CHANGE-ME-IN-PRODUCTION"
    DEFAULT_ADMIN_API_KEY: str = ""

    # ── Logging ──────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # ── Distiller (Celery workers) ───────────────────────────────────────
    DISTILLER_CONCURRENCY: int = 4
    DISTILLER_MAX_RETRIES: int = 3
    DISTILLER_RETRY_BACKOFF: int = 60

    # ── Chunking ─────────────────────────────────────────────────────────
    CHUNK_MAX_TOKENS: int = 1024
    CHUNK_OVERLAP_TOKENS: int = 64

    # ── Incremental Reprocessing ─────────────────────────────────────────
    INCREMENTAL_SIMILARITY_THRESHOLD: float = 0.85
    INCREMENTAL_RECLASSIFY_THRESHOLD: float = 0.20
    PROCESSING_VERSION: int = 1

    # ── MCP Server ───────────────────────────────────────────────────────
    MCP_SERVER_PORT: int = 8002
    MCP_SERVER_TRANSPORT: str = "sse"
    AGENTLAKE_API_URL: str = "http://localhost:8000"
    MCP_SERVER_API_KEY: str = ""

    # ── Entity Graph (Apache AGE) ────────────────────────────────────────
    GRAPH_NAME: str = "agentlake_graph"
    GRAPH_MAX_DEPTH: int = 5

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Accept a comma-separated string or a list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


# ── Singleton accessor ───────────────────────────────────────────────────

_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance (created once)."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings

"""Standalone FastAPI application for the LLM Gateway (Layer 4B).

Runs as a separate container on port 8001.  ALL LLM API keys live
exclusively in this service's environment — no other service has them.

Usage::

    uvicorn agentlake.llm_gateway.app:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.core.database import get_db
from agentlake.llm_gateway.auth import set_service_token, verify_service_token
from agentlake.llm_gateway.providers.registry import ProviderRegistry
from agentlake.llm_gateway.proxy import (
    CompletionRequest,
    EmbeddingRequest,
    GatewayProxy,
)
from agentlake.llm_gateway.rate_limiter import RateLimiter
from agentlake.llm_gateway.token_ledger import TokenLedger

logger = structlog.get_logger(__name__)


# ── Gateway-specific settings ─────────────────────────────────────────────────


class GatewaySettings(BaseSettings):
    """Environment variables for the LLM Gateway container.

    LLM provider API keys are ONLY available here — never in the main API
    or any other service.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database (shared with main app).
    DATABASE_URL: str = (
        "postgresql+asyncpg://agentlake:agentlake_dev@localhost:5432/agentlake"
    )
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5

    # Redis.
    REDIS_URL: str = "redis://localhost:6379/0"

    # Internal auth.
    LLM_GATEWAY_SERVICE_TOKEN: str = ""

    # ── Provider API keys (ONLY in this service) ──────────────────────
    ANTHROPIC_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENAI_COMPAT_BASE_URL: str = ""
    OPENAI_COMPAT_API_KEY: str = ""
    OPENAI_COMPAT_DEFAULT_MODEL: str = "default"

    # ── Routing config ────────────────────────────────────────────────
    LLM_DEFAULT_PROVIDER: str = ""
    LLM_DEFAULT_MODEL: str = ""
    LLM_FALLBACK_CHAIN: str = ""

    # ── Per-task model overrides ─────────────────────────────────────
    LLM_TASK_SUMMARIZE_CHUNK: str = ""
    LLM_TASK_SUMMARIZE_DOCUMENT: str = ""
    LLM_TASK_CLASSIFY_ONTOLOGY: str = ""
    LLM_TASK_EXTRACT_ENTITIES: str = ""
    LLM_TASK_EXTRACT_RELATIONSHIPS: str = ""
    LLM_TASK_EMBED: str = ""

    # ── Rate limiting ─────────────────────────────────────────────────
    LLM_GLOBAL_RATE_LIMIT: int = 500
    LLM_PER_SERVICE_RATE_LIMIT: int = 200

    # ── Logging ───────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"


# ── Pydantic request / response schemas ──────────────────────────────────────


class CompletionRequestSchema(BaseModel):
    """Incoming completion request."""

    messages: list[dict[str, Any]]
    model: str | None = None
    provider: str | None = None
    purpose: str | None = None
    max_tokens: int | None = Field(default=4096, ge=1, le=200000)
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    caller_service: str = "unknown"


class CompletionResponseSchema(BaseModel):
    """Outgoing completion response."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None


class EmbeddingRequestSchema(BaseModel):
    """Incoming embedding request."""

    texts: list[str]
    model: str | None = None
    caller_service: str = "unknown"


class EmbeddingResponseSchema(BaseModel):
    """Outgoing embedding response."""

    embeddings: list[list[float]]
    model: str
    provider: str
    total_tokens: int


class ModelInfoSchema(BaseModel):
    """Model metadata exposed by the /models endpoint."""

    id: str
    provider: str
    display_name: str
    max_tokens: int
    supports_vision: bool = False
    supports_tools: bool = False


class ProviderHealthSchema(BaseModel):
    """Health status for a single provider."""

    provider: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None


class UsageEntrySchema(BaseModel):
    """A single row in a usage report."""

    group_key: str
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float


# ── Singletons (set during lifespan) ─────────────────────────────────────────

_gateway_settings: GatewaySettings | None = None
_registry: ProviderRegistry | None = None
_proxy: GatewayProxy | None = None
_ledger: TokenLedger | None = None
_redis: Redis | None = None


def _get_proxy() -> GatewayProxy:
    assert _proxy is not None, "Gateway proxy not initialized"
    return _proxy


def _get_registry() -> ProviderRegistry:
    assert _registry is not None, "Provider registry not initialized"
    return _registry


def _get_ledger() -> TokenLedger:
    assert _ledger is not None, "Token ledger not initialized"
    return _ledger


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Initialise providers, registry, ledger, and rate limiter on startup."""
    global _gateway_settings, _registry, _proxy, _ledger, _redis  # noqa: PLW0603

    _gateway_settings = GatewaySettings()

    # Auth token.
    set_service_token(_gateway_settings.LLM_GATEWAY_SERVICE_TOKEN)

    # Redis for rate limiting.
    _redis = Redis.from_url(_gateway_settings.REDIS_URL, decode_responses=True)

    # Provider registry.
    _registry = ProviderRegistry()
    _registry.init_from_settings(_gateway_settings)

    if not _registry.provider_names:
        logger.warning(
            "no_providers_configured",
            hint="Set ANTHROPIC_API_KEY, OPENROUTER_API_KEY, or OPENAI_COMPAT_BASE_URL",
        )

    # Token ledger.
    _ledger = TokenLedger()

    # Rate limiter.
    rate_limiter = RateLimiter(redis=_redis)

    # Proxy.
    _proxy = GatewayProxy(
        registry=_registry,
        ledger=_ledger,
        rate_limiter=rate_limiter,
        global_rate_limit=_gateway_settings.LLM_GLOBAL_RATE_LIMIT,
        per_service_rate_limit=_gateway_settings.LLM_PER_SERVICE_RATE_LIMIT,
    )

    logger.info(
        "llm_gateway_started",
        providers=_registry.provider_names,
        fallback_chain=_registry.fallback_chain,
    )

    yield

    # Shutdown.
    if _redis:
        await _redis.aclose()
    logger.info("llm_gateway_stopped")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AgentLake LLM Gateway",
    description="Internal gateway that routes all LLM calls. API keys never leave this service.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.post(
    "/api/v1/llm/complete",
    response_model=CompletionResponseSchema,
    dependencies=[Depends(verify_service_token)],
    tags=["llm"],
)
async def complete(
    request: CompletionRequestSchema,
) -> CompletionResponseSchema:
    """Generate a chat completion.

    Routes the request to the appropriate provider based on model, provider,
    or purpose.  Falls back to the next provider in the chain on failure.
    """
    proxy = _get_proxy()
    req = CompletionRequest(
        messages=request.messages,
        model=request.model,
        provider=request.provider,
        purpose=request.purpose,
        max_tokens=request.max_tokens or 4096,
        temperature=request.temperature if request.temperature is not None else 0.7,
        caller_service=request.caller_service,
    )
    result = await proxy.complete(req)
    return CompletionResponseSchema(
        content=result.content,
        model=result.model,
        provider=result.provider,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
    )


@app.post(
    "/api/v1/llm/embed",
    response_model=EmbeddingResponseSchema,
    dependencies=[Depends(verify_service_token)],
    tags=["llm"],
)
async def embed(
    request: EmbeddingRequestSchema,
) -> EmbeddingResponseSchema:
    """Generate embeddings for a list of texts."""
    proxy = _get_proxy()
    req = EmbeddingRequest(
        texts=request.texts,
        model=request.model,
        caller_service=request.caller_service,
    )
    result = await proxy.embed(req)
    return EmbeddingResponseSchema(
        embeddings=result.embeddings,
        model=result.model,
        provider=result.provider,
        total_tokens=result.total_tokens,
    )


@app.get(
    "/api/v1/llm/usage",
    dependencies=[Depends(verify_service_token)],
    tags=["llm"],
)
async def get_usage(
    start_date: datetime | None = Query(None, description="Start of date range (ISO 8601)"),
    end_date: datetime | None = Query(None, description="End of date range (ISO 8601)"),
    group_by: str = Query("provider", description="Group by: provider, model, caller_service, purpose"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return aggregated LLM usage statistics."""
    ledger = _get_ledger()
    rows = await ledger.get_usage(
        db, start_date=start_date, end_date=end_date, group_by=group_by
    )
    return {
        "data": rows,
        "meta": {"group_by": group_by, "count": len(rows)},
    }


@app.get(
    "/api/v1/llm/models",
    response_model=list[ModelInfoSchema],
    dependencies=[Depends(verify_service_token)],
    tags=["llm"],
)
async def list_models() -> list[ModelInfoSchema]:
    """List all models available across registered providers."""
    registry = _get_registry()
    models = registry.list_all_models()
    return [
        ModelInfoSchema(
            id=m.id,
            provider=m.provider,
            display_name=m.display_name,
            max_tokens=m.max_tokens,
            supports_vision=m.supports_vision,
            supports_tools=m.supports_tools,
        )
        for m in models
    ]


@app.get(
    "/api/v1/llm/providers",
    response_model=list[ProviderHealthSchema],
    dependencies=[Depends(verify_service_token)],
    tags=["llm"],
)
async def provider_health() -> list[ProviderHealthSchema]:
    """Check health of all registered providers."""
    registry = _get_registry()
    results: list[ProviderHealthSchema] = []
    for name in registry.provider_names:
        prov = registry.get_provider(name)
        if prov is not None:
            health = await prov.health_check()
            results.append(
                ProviderHealthSchema(
                    provider=health.provider,
                    healthy=health.healthy,
                    latency_ms=health.latency_ms,
                    error=health.error,
                )
            )
    return results


@app.get("/api/v1/llm/health", tags=["llm"])
async def gateway_health() -> dict[str, Any]:
    """Overall gateway health check (no auth required)."""
    registry = _get_registry()
    return {
        "status": "ok" if registry.provider_names else "degraded",
        "providers": registry.provider_names,
        "fallback_chain": registry.fallback_chain,
    }

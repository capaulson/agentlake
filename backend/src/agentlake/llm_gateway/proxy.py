"""Gateway proxy — routes LLM requests with fallback, rate limiting, and ledger logging."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.llm_gateway.providers.base import EmbeddingResponse as ProviderEmbeddingResponse
from agentlake.llm_gateway.providers.registry import ProviderRegistry
from agentlake.llm_gateway.rate_limiter import RateLimiter
from agentlake.llm_gateway.token_ledger import TokenLedger

logger = structlog.get_logger(__name__)


# ── Request / Response schemas (internal dataclasses) ─────────────────────────


@dataclass
class CompletionRequest:
    """Internal representation of a completion request."""

    messages: list[dict]
    model: str | None = None
    provider: str | None = None
    purpose: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    caller_service: str = "unknown"


@dataclass
class CompletionResponse:
    """Internal representation of a completion response."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None
    finish_reason: str = "stop"


@dataclass
class EmbeddingRequest:
    """Internal representation of an embedding request."""

    texts: list[str]
    model: str | None = None
    caller_service: str = "unknown"


@dataclass
class EmbeddingResponseData:
    """Internal representation of an embedding response."""

    embeddings: list[list[float]]
    model: str
    provider: str
    total_tokens: int


class GatewayProxy:
    """Core request handler that routes LLM calls through the provider registry.

    Responsibilities:
    1. Resolve provider + model from the request.
    2. Enforce rate limits.
    3. Call the provider with automatic fallback on failure.
    4. Log to the token ledger (async, best-effort).
    5. Return a normalized response.
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        ledger: TokenLedger,
        rate_limiter: RateLimiter | None = None,
        *,
        global_rate_limit: int = 500,
        per_service_rate_limit: int = 200,
    ) -> None:
        self._registry = registry
        self._ledger = ledger
        self._rate_limiter = rate_limiter
        self._global_rate_limit = global_rate_limit
        self._per_service_rate_limit = per_service_rate_limit

    # ── Completion ────────────────────────────────────────────────────────

    async def complete(
        self, request: CompletionRequest, db: AsyncSession | None = None
    ) -> CompletionResponse:
        """Route a completion request with fallback and ledger logging.

        Args:
            request: The completion request.
            db: Database session for ledger writes.

        Returns:
            Normalized CompletionResponse.

        Raises:
            Exception: If all providers (including fallbacks) fail.
        """
        # Rate limiting.
        if self._rate_limiter:
            await self._enforce_rate_limit(request.caller_service)

        # Resolve provider.
        provider, resolved_model = self._registry.resolve_provider(
            model=request.model,
            provider=request.provider,
            purpose=request.purpose,
        )

        start = time.monotonic()
        fallback_from: str | None = None

        try:
            result = await provider.complete(
                model=resolved_model,
                messages=request.messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
            latency_ms = int((time.monotonic() - start) * 1000)

            cost = self._registry.estimate_cost(
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            # Log to ledger (best-effort).
            await self._log_to_ledger(
                db=db,
                caller_service=request.caller_service,
                purpose=request.purpose,
                model=result.model,
                provider=result.provider,
                request_type="completion",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
                estimated_cost_usd=cost,
                latency_ms=latency_ms,
                status="success",
                fallback_from=fallback_from,
            )

            return CompletionResponse(
                content=result.content,
                model=result.model,
                provider=result.provider,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
                estimated_cost_usd=cost or None,
                finish_reason=result.finish_reason,
            )

        except Exception as primary_exc:
            logger.warning(
                "primary_provider_failed",
                provider=provider.provider_name,
                model=resolved_model,
                error=str(primary_exc),
            )
            fallback_from = provider.provider_name

            # Try fallback.
            fb_provider = self._registry.get_fallback(provider.provider_name)
            if fb_provider is None:
                # No fallback — log error and re-raise.
                latency_ms = int((time.monotonic() - start) * 1000)
                await self._log_to_ledger(
                    db=db,
                    caller_service=request.caller_service,
                    purpose=request.purpose,
                    model=resolved_model,
                    provider=provider.provider_name,
                    request_type="completion",
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    estimated_cost_usd=None,
                    latency_ms=latency_ms,
                    status="error",
                    error_message=str(primary_exc),
                )
                raise

            # Attempt fallback provider.
            logger.info(
                "attempting_fallback",
                from_provider=provider.provider_name,
                to_provider=fb_provider.provider_name,
            )

            # Resolve a model that the fallback provider can serve.
            fb_model = self._resolve_fallback_model(
                resolved_model, fb_provider.provider_name
            )

            try:
                result = await fb_provider.complete(
                    model=fb_model,
                    messages=request.messages,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                )
                latency_ms = int((time.monotonic() - start) * 1000)

                cost = self._registry.estimate_cost(
                    provider=result.provider,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )

                await self._log_to_ledger(
                    db=db,
                    caller_service=request.caller_service,
                    purpose=request.purpose,
                    model=result.model,
                    provider=result.provider,
                    request_type="completion",
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    total_tokens=result.total_tokens,
                    estimated_cost_usd=cost,
                    latency_ms=latency_ms,
                    status="fallback",
                    fallback_from=fallback_from,
                )

                return CompletionResponse(
                    content=result.content,
                    model=result.model,
                    provider=result.provider,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    total_tokens=result.total_tokens,
                    estimated_cost_usd=cost or None,
                    finish_reason=result.finish_reason,
                )

            except Exception as fb_exc:
                latency_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "fallback_provider_also_failed",
                    provider=fb_provider.provider_name,
                    error=str(fb_exc),
                )
                await self._log_to_ledger(
                    db=db,
                    caller_service=request.caller_service,
                    purpose=request.purpose,
                    model=fb_model,
                    provider=fb_provider.provider_name,
                    request_type="completion",
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    estimated_cost_usd=None,
                    latency_ms=latency_ms,
                    status="error",
                    error_message=f"Primary: {primary_exc}; Fallback: {fb_exc}",
                    fallback_from=fallback_from,
                )
                raise primary_exc from fb_exc

    # ── Embedding ─────────────────────────────────────────────────────────

    async def embed(
        self, request: EmbeddingRequest, db: AsyncSession | None = None
    ) -> EmbeddingResponseData:
        """Route an embedding request.

        Args:
            request: The embedding request.
            db: Database session for ledger writes.

        Returns:
            Normalized EmbeddingResponseData.
        """
        if self._rate_limiter:
            await self._enforce_rate_limit(request.caller_service)

        # For embeddings, resolve with purpose="embed".
        provider, resolved_model = self._registry.resolve_provider(
            model=request.model, purpose="embed"
        )

        start = time.monotonic()

        try:
            result = await provider.embed(texts=request.texts, model=resolved_model)
            latency_ms = int((time.monotonic() - start) * 1000)

            cost = self._registry.estimate_cost(
                provider=result.provider,
                model=result.model,
                input_tokens=result.total_tokens,
                output_tokens=0,
            )

            await self._log_to_ledger(
                db=db,
                caller_service=request.caller_service,
                purpose="embed",
                model=result.model,
                provider=result.provider,
                request_type="embedding",
                input_tokens=result.total_tokens,
                output_tokens=0,
                total_tokens=result.total_tokens,
                estimated_cost_usd=cost,
                latency_ms=latency_ms,
                status="success",
            )

            return EmbeddingResponseData(
                embeddings=result.embeddings,
                model=result.model,
                provider=result.provider,
                total_tokens=result.total_tokens,
            )

        except NotImplementedError:
            # Provider doesn't support embeddings — try fallback.
            fb_provider = self._registry.get_fallback(provider.provider_name)
            if fb_provider is None:
                raise

            fb_model = request.model or "openai/text-embedding-3-small"
            result = await fb_provider.embed(texts=request.texts, model=fb_model)
            latency_ms = int((time.monotonic() - start) * 1000)

            cost = self._registry.estimate_cost(
                provider=result.provider,
                model=result.model,
                input_tokens=result.total_tokens,
                output_tokens=0,
            )

            await self._log_to_ledger(
                db=db,
                caller_service=request.caller_service,
                purpose="embed",
                model=result.model,
                provider=result.provider,
                request_type="embedding",
                input_tokens=result.total_tokens,
                output_tokens=0,
                total_tokens=result.total_tokens,
                estimated_cost_usd=cost,
                latency_ms=latency_ms,
                status="fallback",
                fallback_from=provider.provider_name,
            )

            return EmbeddingResponseData(
                embeddings=result.embeddings,
                model=result.model,
                provider=result.provider,
                total_tokens=result.total_tokens,
            )

    # ── Internals ─────────────────────────────────────────────────────────

    async def _enforce_rate_limit(self, caller_service: str) -> None:
        """Check rate limits and raise if exceeded."""
        from agentlake.core.exceptions import RateLimitError

        if self._rate_limiter is None:
            return

        # Global limit.
        allowed, remaining, reset = await self._rate_limiter.check_rate_limit(
            key="global",
            limit=self._global_rate_limit,
            window_seconds=60,
            scope="global",
        )
        if not allowed:
            raise RateLimitError(
                f"Global rate limit exceeded. Retry in {reset}s."
            )

        # Per-service limit.
        allowed, remaining, reset = await self._rate_limiter.check_rate_limit(
            key=caller_service,
            limit=self._per_service_rate_limit,
            window_seconds=60,
            scope="per_service",
        )
        if not allowed:
            raise RateLimitError(
                f"Per-service rate limit exceeded for '{caller_service}'. "
                f"Retry in {reset}s."
            )

    def _resolve_fallback_model(
        self, original_model: str, fallback_provider: str
    ) -> str:
        """Map a model to an equivalent on the fallback provider.

        For example, ``claude-sonnet-4-20250514`` on anthropic becomes
        ``anthropic/claude-sonnet-4-20250514`` on openrouter.
        """
        if fallback_provider == "openrouter" and not original_model.startswith(
            ("anthropic/", "openai/", "google/", "meta-llama/", "mistral/")
        ):
            return f"anthropic/{original_model}"
        if fallback_provider == "anthropic" and original_model.startswith("anthropic/"):
            return original_model.removeprefix("anthropic/")
        return original_model

    async def _log_to_ledger(
        self,
        db: AsyncSession | None,
        **kwargs: Any,
    ) -> None:
        """Best-effort ledger logging — never raises."""
        if db is None:
            return
        try:
            await self._ledger.log_request(db, **kwargs)
        except Exception as exc:
            logger.error("ledger_write_failed", error=str(exc))

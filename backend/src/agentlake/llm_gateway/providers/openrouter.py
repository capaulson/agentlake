"""OpenRouter provider adapter using httpx (OpenAI-compatible API)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from agentlake.llm_gateway.providers.base import (
    EmbeddingResponse,
    ModelInfo,
    ProviderHealth,
    ProviderResponse,
)

logger = structlog.get_logger(__name__)

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider:
    """Provider adapter for OpenRouter (OpenAI-compatible format).

    OpenRouter aggregates dozens of model providers behind a single
    OpenAI-compatible API, making it ideal as a fallback or for accessing
    models not available through Anthropic directly.
    """

    provider_name: str = "openrouter"

    def __init__(
        self,
        api_key: str,
        base_url: str = _BASE_URL,
        http_referer: str = "https://agentlake.dev",
        x_title: str = "AgentLake",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": http_referer,
            "X-Title": x_title,
            "Content-Type": "application/json",
        }
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=600.0,
        )

    # ── Completion ────────────────────────────────────────────────────────

    async def complete(
        self, model: str, messages: list[dict], **kwargs: object
    ) -> ProviderResponse:
        """Send a chat completion request to OpenRouter.

        Args:
            model: Model identifier (e.g. ``anthropic/claude-sonnet-4-20250514``).
            messages: OpenAI-format message list.
            **kwargs: Additional parameters (max_tokens, temperature, etc.).
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if "max_tokens" in kwargs:
            payload["max_tokens"] = int(kwargs["max_tokens"])  # type: ignore[arg-type]
        if "temperature" in kwargs:
            payload["temperature"] = float(kwargs["temperature"])  # type: ignore[arg-type]

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "openrouter_api_error",
                status_code=exc.response.status_code,
                body=exc.response.text[:500],
                model=model,
            )
            raise
        except httpx.HTTPError as exc:
            logger.error("openrouter_connection_error", message=str(exc), model=model)
            raise

        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # Handle reasoning models (e.g. Nemotron Super) that put output
        # in the 'reasoning' field instead of 'content'.
        message = choice["message"]
        content = message.get("content") or ""
        if not content:
            content = message.get("reasoning", "")

        return ProviderResponse(
            content=content,
            model=data.get("model", model),
            provider=self.provider_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            raw_response=data,
            finish_reason=choice.get("finish_reason", "stop") or "stop",
        )

    # ── Embeddings ────────────────────────────────────────────────────────

    async def embed(
        self, texts: list[str], model: str | None = None
    ) -> EmbeddingResponse:
        """Generate embeddings via OpenRouter's embeddings endpoint.

        Args:
            texts: Texts to embed.
            model: Embedding model (defaults to a common embedding model).
        """
        embed_model = model or "openai/text-embedding-3-small"
        payload: dict[str, Any] = {
            "model": embed_model,
            "input": texts,
        }

        try:
            resp = await self._client.post("/embeddings", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "openrouter_embed_error",
                status_code=exc.response.status_code,
                body=exc.response.text[:500],
                model=embed_model,
            )
            raise
        except httpx.HTTPError as exc:
            logger.error(
                "openrouter_embed_connection_error", message=str(exc), model=embed_model
            )
            raise

        data = resp.json()
        embeddings = [item["embedding"] for item in data["data"]]
        total_tokens = data.get("usage", {}).get("total_tokens", 0)

        return EmbeddingResponse(
            embeddings=embeddings,
            model=embed_model,
            provider=self.provider_name,
            total_tokens=total_tokens,
        )

    # ── Model catalogue ───────────────────────────────────────────────────

    def list_models(self) -> list[ModelInfo]:
        """Return a curated list of popular models available on OpenRouter."""
        return [
            ModelInfo(
                id="anthropic/claude-sonnet-4-20250514",
                provider=self.provider_name,
                display_name="Claude Sonnet 4 (via OpenRouter)",
                max_tokens=8192,
                supports_vision=True,
                supports_tools=True,
            ),
            ModelInfo(
                id="openai/gpt-4o",
                provider=self.provider_name,
                display_name="GPT-4o (via OpenRouter)",
                max_tokens=4096,
                supports_vision=True,
                supports_tools=True,
            ),
            ModelInfo(
                id="openai/text-embedding-3-small",
                provider=self.provider_name,
                display_name="text-embedding-3-small (via OpenRouter)",
                max_tokens=8191,
            ),
            ModelInfo(
                id="google/gemini-2.0-flash-001",
                provider=self.provider_name,
                display_name="Gemini 2.0 Flash (via OpenRouter)",
                max_tokens=8192,
                supports_vision=True,
                supports_tools=True,
            ),
        ]

    # ── Health check ──────────────────────────────────────────────────────

    async def health_check(self) -> ProviderHealth:
        """Check connectivity to OpenRouter by listing models."""
        start = time.monotonic()
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.provider_name, healthy=True, latency_ms=latency
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.provider_name,
                healthy=False,
                latency_ms=latency,
                error=str(exc),
            )

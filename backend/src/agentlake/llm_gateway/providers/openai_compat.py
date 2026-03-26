"""Generic OpenAI-compatible provider adapter.

Works with vLLM, Ollama, LM Studio, text-generation-inference, and any
other server that implements the OpenAI chat completions / embeddings API.
"""

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


class OpenAICompatProvider:
    """Provider adapter for any OpenAI-compatible API endpoint.

    Args:
        base_url: Root URL of the API (e.g. ``http://localhost:11434/v1``).
        api_key: Bearer token, if required.  Defaults to empty string.
        default_model: Fallback model ID when none is specified in a request.
    """

    provider_name: str = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        default_model: str = "default",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=120.0,
        )

    # ── Completion ────────────────────────────────────────────────────────

    async def complete(
        self, model: str, messages: list[dict], **kwargs: object
    ) -> ProviderResponse:
        """Send a chat completion to the OpenAI-compatible endpoint.

        Args:
            model: Model identifier.
            messages: OpenAI-format message list.
            **kwargs: Additional params (max_tokens, temperature, etc.).
        """
        resolved_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": resolved_model,
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
                "openai_compat_api_error",
                status_code=exc.response.status_code,
                body=exc.response.text[:500],
                model=resolved_model,
            )
            raise
        except httpx.HTTPError as exc:
            logger.error(
                "openai_compat_connection_error",
                message=str(exc),
                model=resolved_model,
            )
            raise

        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        return ProviderResponse(
            content=choice["message"]["content"] or "",
            model=data.get("model", resolved_model),
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
        """Generate embeddings via the /embeddings endpoint.

        Args:
            texts: Strings to embed.
            model: Optional model override (defaults to ``self._default_model``).
        """
        embed_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": embed_model,
            "input": texts,
        }

        try:
            resp = await self._client.post("/embeddings", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "openai_compat_embed_error",
                status_code=exc.response.status_code,
                body=exc.response.text[:500],
                model=embed_model,
            )
            raise
        except httpx.HTTPError as exc:
            logger.error(
                "openai_compat_embed_connection_error",
                message=str(exc),
                model=embed_model,
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
        """Return a placeholder list; self-hosted models vary by deployment."""
        return [
            ModelInfo(
                id=self._default_model,
                provider=self.provider_name,
                display_name=f"{self._default_model} (self-hosted)",
                max_tokens=4096,
            ),
        ]

    # ── Health check ──────────────────────────────────────────────────────

    async def health_check(self) -> ProviderHealth:
        """Check connectivity by listing models."""
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

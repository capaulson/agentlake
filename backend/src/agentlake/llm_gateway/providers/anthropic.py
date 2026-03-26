"""Anthropic provider adapter using the official SDK."""

from __future__ import annotations

import time

import anthropic
import structlog

from agentlake.llm_gateway.providers.base import (
    EmbeddingResponse,
    ModelInfo,
    ProviderHealth,
    ProviderResponse,
)

logger = structlog.get_logger(__name__)


class AnthropicProvider:
    """Provider adapter for Anthropic's Claude models.

    Uses the official ``anthropic`` SDK (async client) to communicate with
    the Anthropic Messages API.
    """

    provider_name: str = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    # ── Completion ────────────────────────────────────────────────────────

    async def complete(
        self, model: str, messages: list[dict], **kwargs: object
    ) -> ProviderResponse:
        """Call the Anthropic Messages API.

        Args:
            model: Claude model identifier (e.g. ``claude-sonnet-4-20250514``).
            messages: OpenAI-style message list.  A leading ``system`` role
                message is extracted and sent as the ``system`` parameter.
            **kwargs: Passed through (``max_tokens``, ``temperature``, etc.).
        """
        # Extract system message if present.
        system_prompt: str | None = None
        api_messages: list[dict] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                api_messages.append(msg)

        max_tokens = int(kwargs.pop("max_tokens", 4096))  # type: ignore[arg-type]
        temperature = kwargs.pop("temperature", None)

        create_kwargs: dict = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            create_kwargs["system"] = system_prompt
        if temperature is not None:
            create_kwargs["temperature"] = float(temperature)  # type: ignore[arg-type]

        try:
            response = await self._client.messages.create(**create_kwargs)
        except anthropic.APIStatusError as exc:
            logger.error(
                "anthropic_api_error",
                status_code=exc.status_code,
                message=str(exc),
                model=model,
            )
            raise
        except anthropic.APIConnectionError as exc:
            logger.error("anthropic_connection_error", message=str(exc), model=model)
            raise

        # Combine content blocks (may include text + tool_use).
        content_parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)

        return ProviderResponse(
            content="".join(content_parts),
            model=response.model,
            provider=self.provider_name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else {},
            finish_reason=response.stop_reason or "stop",
        )

    # ── Embeddings ────────────────────────────────────────────────────────

    async def embed(
        self, texts: list[str], model: str | None = None
    ) -> EmbeddingResponse:
        """Anthropic does not offer a native embeddings endpoint.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "Anthropic does not provide a native embeddings API. "
            "Use OpenRouter or an OpenAI-compatible provider for embeddings."
        )

    # ── Model catalogue ───────────────────────────────────────────────────

    def list_models(self) -> list[ModelInfo]:
        """Return the set of Claude models exposed by this provider."""
        return [
            ModelInfo(
                id="claude-opus-4-20250514",
                provider=self.provider_name,
                display_name="Claude Opus 4",
                max_tokens=32768,
                supports_vision=True,
                supports_tools=True,
            ),
            ModelInfo(
                id="claude-sonnet-4-20250514",
                provider=self.provider_name,
                display_name="Claude Sonnet 4",
                max_tokens=16384,
                supports_vision=True,
                supports_tools=True,
            ),
            ModelInfo(
                id="claude-haiku-4-20250514",
                provider=self.provider_name,
                display_name="Claude Haiku 4",
                max_tokens=8192,
                supports_vision=True,
                supports_tools=True,
            ),
            ModelInfo(
                id="claude-sonnet-4-20250514",
                provider=self.provider_name,
                display_name="Claude 3.5 Sonnet",
                max_tokens=8192,
                supports_vision=True,
                supports_tools=True,
            ),
        ]

    # ── Health check ──────────────────────────────────────────────────────

    async def health_check(self) -> ProviderHealth:
        """Perform a lightweight health check against the Anthropic API.

        Sends a minimal completion request to verify connectivity and auth.
        """
        start = time.monotonic()
        try:
            await self._client.messages.create(
                model="claude-haiku-4-20250514",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
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

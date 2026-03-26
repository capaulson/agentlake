"""Base types and protocol for LLM providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ProviderResponse:
    """Normalized response from any LLM provider completion call."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    raw_response: dict = field(default_factory=dict)
    finish_reason: str = "stop"


@dataclass
class EmbeddingResponse:
    """Normalized response from any LLM provider embedding call."""

    embeddings: list[list[float]]
    model: str
    provider: str
    total_tokens: int


@dataclass
class ModelInfo:
    """Metadata about a model available through a provider."""

    id: str
    provider: str
    display_name: str
    max_tokens: int
    supports_vision: bool = False
    supports_tools: bool = False


@dataclass
class ProviderHealth:
    """Health check result for a provider."""

    provider: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that every LLM provider adapter must implement.

    Each provider translates between AgentLake's normalized request/response
    types and the provider's native API.
    """

    provider_name: str

    async def complete(
        self, model: str, messages: list[dict], **kwargs: object
    ) -> ProviderResponse:
        """Generate a chat completion.

        Args:
            model: Model identifier (e.g. ``claude-sonnet-4-20250514``).
            messages: OpenAI-style message list.
            **kwargs: Provider-specific options (max_tokens, temperature, etc.).

        Returns:
            Normalized ProviderResponse.
        """
        ...

    async def embed(
        self, texts: list[str], model: str | None = None
    ) -> EmbeddingResponse:
        """Generate embeddings for a list of texts.

        Args:
            texts: Strings to embed.
            model: Optional model override.

        Returns:
            Normalized EmbeddingResponse.
        """
        ...

    def list_models(self) -> list[ModelInfo]:
        """Return the static list of models this provider exposes."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check whether the provider is reachable and healthy."""
        ...

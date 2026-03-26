"""LLM Gateway client — the ONLY module other services use to call LLMs.

CRITICAL INVARIANT: No service may import or call an LLM provider SDK
directly.  All LLM requests go through this client, which forwards them
to the LLM Gateway service (Layer 4B).

Usage::

    from agentlake.services.llm_client import LLMClient

    client = LLMClient(
        gateway_url="http://llm-gateway:8001",
        service_token="...",
        service_name="distiller",
    )
    result = await client.complete(
        messages=[{"role": "user", "content": "Summarize this text..."}],
        purpose="summarize",
    )
    print(result.content)
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from agentlake.core.exceptions import LLMGatewayError

logger = structlog.get_logger(__name__)


@dataclass
class CompletionResult:
    """Normalized result from an LLM completion call."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None


class LLMClient:
    """HTTP client for the LLM Gateway.

    All LLM calls in AgentLake go through this client.  It communicates
    exclusively with the LLM Gateway service over HTTP and never touches
    provider SDKs or API keys.

    Args:
        gateway_url: Base URL of the LLM Gateway (e.g. ``http://llm-gateway:8001``).
        service_token: Shared secret for ``X-Service-Token`` auth.
        service_name: Identifier for the calling service (used in ledger).
    """

    def __init__(
        self,
        gateway_url: str,
        service_token: str,
        service_name: str = "api",
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.service_token = service_token
        self.service_name = service_name
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=10.0),
            headers={
                "X-Service-Token": service_token,
                "Content-Type": "application/json",
            },
        )

    # ── Completion ────────────────────────────────────────────────────────

    async def complete(
        self,
        messages: list[dict],
        purpose: str,
        *,
        model: str | None = None,
        provider: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> CompletionResult:
        """Send a completion request to the LLM Gateway.

        Args:
            messages: OpenAI-style message list.
            purpose: Task purpose (e.g. ``summarize``, ``classify``).  This
                is the primary routing key — it maps to a model via the
                gateway's task routing config.
            model: Optional explicit model override.
            provider: Optional explicit provider override.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.

        Returns:
            Normalized CompletionResult.

        Raises:
            LLMGatewayError: On HTTP errors or unexpected failures.
        """
        url = f"{self.gateway_url}/api/v1/llm/complete"
        payload = {
            "messages": messages,
            "purpose": purpose,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "caller_service": self.service_name,
        }
        if model is not None:
            payload["model"] = model
        if provider is not None:
            payload["provider"] = provider

        try:
            resp = await self._client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            logger.error(
                "llm_gateway_timeout",
                url=url,
                purpose=purpose,
                error=str(exc),
            )
            raise LLMGatewayError(
                f"LLM Gateway request timed out: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "llm_gateway_connection_error",
                url=url,
                purpose=purpose,
                error=str(exc),
            )
            raise LLMGatewayError(
                f"Failed to connect to LLM Gateway: {exc}"
            ) from exc

        if resp.status_code != 200:
            body = resp.text[:500]
            logger.error(
                "llm_gateway_error_response",
                status_code=resp.status_code,
                body=body,
                purpose=purpose,
            )
            raise LLMGatewayError(
                f"LLM Gateway returned {resp.status_code}: {body}"
            )

        data = resp.json()
        logger.debug(
            "llm_completion_received",
            purpose=purpose,
            model=data.get("model"),
            provider=data.get("provider"),
            tokens=data.get("total_tokens"),
        )

        return CompletionResult(
            content=data["content"],
            model=data["model"],
            provider=data["provider"],
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
            total_tokens=data["total_tokens"],
            estimated_cost_usd=data.get("estimated_cost_usd"),
        )

    # ── Embeddings ────────────────────────────────────────────────────────

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings via the LLM Gateway.

        Args:
            texts: Strings to embed.
            model: Optional model override.

        Returns:
            List of embedding vectors (one per input text).

        Raises:
            LLMGatewayError: On HTTP errors or unexpected failures.
        """
        url = f"{self.gateway_url}/api/v1/llm/embed"
        payload: dict = {
            "texts": texts,
            "caller_service": self.service_name,
        }
        if model is not None:
            payload["model"] = model

        try:
            resp = await self._client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            logger.error("llm_gateway_embed_timeout", url=url, error=str(exc))
            raise LLMGatewayError(
                f"LLM Gateway embedding request timed out: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "llm_gateway_embed_connection_error", url=url, error=str(exc)
            )
            raise LLMGatewayError(
                f"Failed to connect to LLM Gateway for embeddings: {exc}"
            ) from exc

        if resp.status_code != 200:
            body = resp.text[:500]
            logger.error(
                "llm_gateway_embed_error_response",
                status_code=resp.status_code,
                body=body,
            )
            raise LLMGatewayError(
                f"LLM Gateway returned {resp.status_code} for embeddings: {body}"
            )

        data = resp.json()
        logger.debug(
            "llm_embeddings_received",
            model=data.get("model"),
            count=len(data.get("embeddings", [])),
            tokens=data.get("total_tokens"),
        )

        return data["embeddings"]

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

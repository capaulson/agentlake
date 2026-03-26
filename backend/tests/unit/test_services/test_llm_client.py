"""Tests for LLMClient with mocked HTTP using respx."""

from __future__ import annotations

import httpx
import pytest
import respx

from agentlake.core.exceptions import LLMGatewayError
from agentlake.services.llm_client import CompletionResult, LLMClient


@pytest.fixture()
def llm_client() -> LLMClient:
    return LLMClient(
        gateway_url="http://llm-gateway:8001",
        service_token="test-token-abc",
        service_name="test-service",
    )


class TestLLMClientComplete:
    """Tests for the complete() method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_complete_sends_correct_request(self, llm_client: LLMClient) -> None:
        route = respx.post("http://llm-gateway:8001/api/v1/llm/complete").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": "Summary of the text.",
                    "model": "claude-sonnet-4-20250514",
                    "provider": "anthropic",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "estimated_cost_usd": 0.001,
                },
            )
        )

        result = await llm_client.complete(
            messages=[{"role": "user", "content": "Summarize this."}],
            purpose="summarize",
        )

        assert isinstance(result, CompletionResult)
        assert result.content == "Summary of the text."
        assert result.model == "claude-sonnet-4-20250514"
        assert result.provider == "anthropic"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150
        assert route.called

        # Verify the request payload
        request_body = route.calls.last.request.content
        import json

        payload = json.loads(request_body)
        assert payload["purpose"] == "summarize"
        assert payload["caller_service"] == "test-service"

    @respx.mock
    @pytest.mark.asyncio
    async def test_complete_sends_service_token_header(self, llm_client: LLMClient) -> None:
        respx.post("http://llm-gateway:8001/api/v1/llm/complete").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": "ok",
                    "model": "test",
                    "provider": "test",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                },
            )
        )

        await llm_client.complete(
            messages=[{"role": "user", "content": "hi"}], purpose="chat"
        )

        request = respx.calls.last.request
        assert request.headers["X-Service-Token"] == "test-token-abc"

    @respx.mock
    @pytest.mark.asyncio
    async def test_complete_handles_error_response(self, llm_client: LLMClient) -> None:
        respx.post("http://llm-gateway:8001/api/v1/llm/complete").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        with pytest.raises(LLMGatewayError, match="500"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "fail"}], purpose="test"
            )

    @respx.mock
    @pytest.mark.asyncio
    async def test_complete_handles_timeout(self, llm_client: LLMClient) -> None:
        respx.post("http://llm-gateway:8001/api/v1/llm/complete").mock(
            side_effect=httpx.TimeoutException("request timed out")
        )

        with pytest.raises(LLMGatewayError, match="timed out"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "slow"}], purpose="test"
            )

    @respx.mock
    @pytest.mark.asyncio
    async def test_complete_handles_connection_error(self, llm_client: LLMClient) -> None:
        respx.post("http://llm-gateway:8001/api/v1/llm/complete").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(LLMGatewayError, match="Failed to connect"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "no conn"}], purpose="test"
            )

    @respx.mock
    @pytest.mark.asyncio
    async def test_complete_with_explicit_model(self, llm_client: LLMClient) -> None:
        route = respx.post("http://llm-gateway:8001/api/v1/llm/complete").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": "ok",
                    "model": "claude-opus-4-20250514",
                    "provider": "anthropic",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                },
            )
        )

        await llm_client.complete(
            messages=[{"role": "user", "content": "hi"}],
            purpose="test",
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

        import json

        payload = json.loads(route.calls.last.request.content)
        assert payload["model"] == "claude-opus-4-20250514"
        assert payload["provider"] == "anthropic"


class TestLLMClientEmbed:
    """Tests for the embed() method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_embed_returns_embeddings(self, llm_client: LLMClient) -> None:
        mock_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        respx.post("http://llm-gateway:8001/api/v1/llm/embed").mock(
            return_value=httpx.Response(
                200,
                json={
                    "embeddings": mock_embeddings,
                    "model": "text-embedding-3-small",
                    "total_tokens": 10,
                },
            )
        )

        result = await llm_client.embed(["hello", "world"])
        assert result == mock_embeddings

    @respx.mock
    @pytest.mark.asyncio
    async def test_embed_handles_error(self, llm_client: LLMClient) -> None:
        respx.post("http://llm-gateway:8001/api/v1/llm/embed").mock(
            return_value=httpx.Response(500, text="Error")
        )

        with pytest.raises(LLMGatewayError):
            await llm_client.embed(["fail"])

    @respx.mock
    @pytest.mark.asyncio
    async def test_embed_handles_timeout(self, llm_client: LLMClient) -> None:
        respx.post("http://llm-gateway:8001/api/v1/llm/embed").mock(
            side_effect=httpx.TimeoutException("timeout")
        )

        with pytest.raises(LLMGatewayError, match="timed out"):
            await llm_client.embed(["timeout"])


class TestLLMClientLifecycle:
    """Tests for client lifecycle management."""

    @pytest.mark.asyncio
    async def test_close(self, llm_client: LLMClient) -> None:
        await llm_client.close()
        # Should not raise

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        async with LLMClient(
            gateway_url="http://test:8001",
            service_token="token",
        ) as client:
            assert client.gateway_url == "http://test:8001"
        # Should close without error

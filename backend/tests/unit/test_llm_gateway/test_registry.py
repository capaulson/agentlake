"""Tests for the LLM Gateway ProviderRegistry."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from agentlake.llm_gateway.providers.base import (
    EmbeddingResponse,
    LLMProvider,
    ModelInfo,
    ProviderHealth,
    ProviderResponse,
)
from agentlake.llm_gateway.providers.registry import ProviderRegistry


class FakeProvider:
    """Fake provider for testing."""

    def __init__(self, name: str = "fake") -> None:
        self.provider_name = name

    async def complete(self, model: str, messages: list[dict], **kwargs: object) -> ProviderResponse:
        return ProviderResponse(
            content="fake response",
            model=model,
            provider=self.provider_name,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )

    async def embed(self, texts: list[str], model: str | None = None) -> EmbeddingResponse:
        return EmbeddingResponse(
            embeddings=[[0.1] * 3 for _ in texts],
            model=model or "fake-embed",
            provider=self.provider_name,
            total_tokens=len(texts) * 5,
        )

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id="fake-model",
                provider=self.provider_name,
                display_name="Fake Model",
                max_tokens=4096,
            )
        ]

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider=self.provider_name, healthy=True, latency_ms=10.0)


class TestProviderRegistry:
    """Tests for ProviderRegistry."""

    def setup_method(self) -> None:
        self.registry = ProviderRegistry()

    # ── Registration ──────────────────────────────────────────────────────

    def test_register_provider(self) -> None:
        prov = FakeProvider("test_prov")
        self.registry.register_provider(prov)
        assert "test_prov" in self.registry.provider_names

    def test_get_provider(self) -> None:
        prov = FakeProvider("test_prov")
        self.registry.register_provider(prov)
        assert self.registry.get_provider("test_prov") is prov

    def test_get_provider_not_found(self) -> None:
        assert self.registry.get_provider("missing") is None

    def test_provider_names_empty(self) -> None:
        assert self.registry.provider_names == []

    # ── Model pattern matching ────────────────────────────────────────────

    def test_claude_pattern_matches_anthropic(self) -> None:
        prov = FakeProvider("anthropic")
        self.registry.register_provider(prov)
        resolved_prov, model = self.registry.resolve_provider(model="claude-sonnet-4-20250514")
        assert resolved_prov is prov
        assert model == "claude-sonnet-4-20250514"

    def test_openai_pattern_matches_openrouter(self) -> None:
        prov = FakeProvider("openrouter")
        self.registry.register_provider(prov)
        resolved_prov, model = self.registry.resolve_provider(model="openai/gpt-4o")
        assert resolved_prov is prov

    def test_google_pattern_matches_openrouter(self) -> None:
        prov = FakeProvider("openrouter")
        self.registry.register_provider(prov)
        resolved_prov, model = self.registry.resolve_provider(model="google/gemini-2.0-flash-001")
        assert resolved_prov is prov

    # ── Task routing ──────────────────────────────────────────────────────

    def test_summarize_routes_to_claude_sonnet(self) -> None:
        prov = FakeProvider("anthropic")
        self.registry.register_provider(prov)
        resolved_prov, model = self.registry.resolve_provider(purpose="summarize")
        assert model == "claude-sonnet-4-20250514"
        assert resolved_prov is prov

    def test_embed_routes_to_openrouter(self) -> None:
        prov = FakeProvider("openrouter")
        self.registry.register_provider(prov)
        resolved_prov, model = self.registry.resolve_provider(purpose="embed")
        assert model == "openai/text-embedding-3-small"
        assert resolved_prov is prov

    def test_classify_routes_to_haiku(self) -> None:
        prov = FakeProvider("anthropic")
        self.registry.register_provider(prov)
        resolved_prov, model = self.registry.resolve_provider(purpose="classify")
        assert model == "claude-haiku-4-20250514"

    def test_unknown_purpose_no_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot resolve provider"):
            self.registry.resolve_provider(purpose="unknown_task")

    # ── Explicit provider ─────────────────────────────────────────────────

    def test_explicit_provider(self) -> None:
        prov = FakeProvider("anthropic")
        self.registry.register_provider(prov)
        resolved_prov, model = self.registry.resolve_provider(
            provider="anthropic", model="claude-sonnet-4-20250514"
        )
        assert resolved_prov is prov

    def test_explicit_provider_not_registered_raises(self) -> None:
        with pytest.raises(ValueError, match="not registered"):
            self.registry.resolve_provider(provider="missing", model="test")

    def test_explicit_provider_no_model_raises(self) -> None:
        prov = FakeProvider("anthropic")
        self.registry.register_provider(prov)
        with pytest.raises(ValueError, match="Cannot resolve model"):
            self.registry.resolve_provider(provider="anthropic")

    # ── Fallback chain ────────────────────────────────────────────────────

    def test_fallback_chain(self) -> None:
        prov1 = FakeProvider("anthropic")
        prov2 = FakeProvider("openrouter")
        self.registry.register_provider(prov1)
        self.registry.register_provider(prov2)
        self.registry.fallback_chain = ["anthropic", "openrouter"]

        fallback = self.registry.get_fallback("anthropic")
        assert fallback is prov2

    def test_fallback_returns_none_at_end(self) -> None:
        prov = FakeProvider("anthropic")
        self.registry.register_provider(prov)
        self.registry.fallback_chain = ["anthropic"]

        assert self.registry.get_fallback("anthropic") is None

    def test_fallback_for_unknown_provider(self) -> None:
        prov = FakeProvider("anthropic")
        self.registry.register_provider(prov)
        self.registry.fallback_chain = ["anthropic"]

        fallback = self.registry.get_fallback("unknown")
        assert fallback is prov

    # ── Cost estimation ───────────────────────────────────────────────────

    def test_estimate_cost_claude_sonnet(self) -> None:
        cost = self.registry.estimate_cost(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
        )
        # $0.003/1k input + $0.015/1k output = $0.003 + $0.0075 = $0.0105
        assert cost == pytest.approx(0.0105, abs=0.001)

    def test_estimate_cost_unknown_model(self) -> None:
        cost = self.registry.estimate_cost(
            provider="unknown",
            model="unknown-model",
            input_tokens=1000,
            output_tokens=500,
        )
        assert cost == 0.0

    def test_estimate_cost_opus(self) -> None:
        cost = self.registry.estimate_cost(
            provider="anthropic",
            model="claude-opus-4-20250514",
            input_tokens=1000,
            output_tokens=1000,
        )
        # $0.015/1k input + $0.075/1k output = $0.015 + $0.075 = $0.09
        assert cost == pytest.approx(0.09, abs=0.001)

    # ── List models ───────────────────────────────────────────────────────

    def test_list_all_models(self) -> None:
        self.registry.register_provider(FakeProvider("p1"))
        self.registry.register_provider(FakeProvider("p2"))
        models = self.registry.list_all_models()
        assert len(models) == 2

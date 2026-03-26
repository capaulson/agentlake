"""Provider registry with model routing, task routing, and fallback logic."""

from __future__ import annotations

import fnmatch
from typing import Any

import structlog

from agentlake.llm_gateway.providers.base import LLMProvider, ModelInfo

logger = structlog.get_logger(__name__)


# ── Pricing table (USD per 1 000 tokens) ─────────────────────────────────────
# Format: (provider, model_glob) -> (input_price, output_price)
_DEFAULT_PRICING: dict[tuple[str, str], tuple[float, float]] = {
    ("anthropic", "claude-opus-4-*"): (0.015, 0.075),
    ("anthropic", "claude-sonnet-4-*"): (0.003, 0.015),
    ("anthropic", "claude-haiku-4-*"): (0.0008, 0.004),
    ("openrouter", "anthropic/claude-sonnet-4-*"): (0.003, 0.015),
    ("openrouter", "openai/gpt-4o"): (0.0025, 0.010),
    ("openrouter", "openai/text-embedding-3-small"): (0.00002, 0.0),
    ("openrouter", "google/gemini-2.0-flash-*"): (0.0001, 0.0004),
}

# ── Default task -> model mapping ─────────────────────────────────────────────
_DEFAULT_TASK_ROUTES: dict[str, str] = {
    "summarize": "claude-sonnet-4-20250514",
    "extract_entities": "claude-sonnet-4-20250514",
    "classify": "claude-haiku-4-20250514",
    "embed": "openai/text-embedding-3-small",
    "chat": "claude-sonnet-4-20250514",
    "generate_frontmatter": "claude-sonnet-4-20250514",
    "rewrite": "claude-sonnet-4-20250514",
}

# ── Default model glob -> provider mapping ────────────────────────────────────
_DEFAULT_MODEL_ROUTES: dict[str, str] = {
    "claude-*": "anthropic",
    "anthropic/*": "openrouter",
    "openai/*": "openrouter",
    "nvidia/*": "openrouter",
    "google/*": "openrouter",
    "meta-llama/*": "openrouter",
    "google/*": "openrouter",
    "meta-llama/*": "openrouter",
    "mistral/*": "openrouter",
}


class ProviderRegistry:
    """Central registry that maps models, tasks, and purposes to providers.

    Responsibilities:
    - Register/unregister providers.
    - Resolve (provider, model) from purpose, model name, or explicit provider.
    - Provide fallback chain on failure.
    - Estimate cost using a pricing table.
    """

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self.model_routes: dict[str, str] = dict(_DEFAULT_MODEL_ROUTES)
        self.task_routes: dict[str, str] = dict(_DEFAULT_TASK_ROUTES)
        self.fallback_chain: list[str] = []
        self.pricing: dict[tuple[str, str], tuple[float, float]] = dict(
            _DEFAULT_PRICING
        )

    # ── Provider management ───────────────────────────────────────────────

    def register_provider(self, provider: LLMProvider) -> None:
        """Register a provider adapter by its ``provider_name``.

        Args:
            provider: An object implementing the LLMProvider protocol.
        """
        name = provider.provider_name
        self._providers[name] = provider
        logger.info("provider_registered", provider=name)

    def get_provider(self, name: str) -> LLMProvider | None:
        """Return a registered provider by name, or ``None``."""
        return self._providers.get(name)

    @property
    def provider_names(self) -> list[str]:
        """Return names of all registered providers."""
        return list(self._providers.keys())

    # ── Resolution ────────────────────────────────────────────────────────

    def resolve_provider(
        self,
        model: str | None = None,
        provider: str | None = None,
        purpose: str | None = None,
    ) -> tuple[LLMProvider, str]:
        """Resolve a provider instance and model string.

        Resolution order:
        1. If *provider* is explicitly given, use it; model must also be given
           or derivable from *purpose*.
        2. If *purpose* is given, look up task_routes for a model, then resolve
           the provider for that model via model_routes.
        3. If *model* is given, match against model_routes glob patterns.
        4. Fall back to the first provider in the fallback chain.

        Args:
            model: Explicit model identifier.
            provider: Explicit provider name.
            purpose: Task/purpose name (e.g. ``summarize``).

        Returns:
            Tuple of (provider_instance, resolved_model).

        Raises:
            ValueError: If no provider can be resolved.
        """
        resolved_model = model

        # Step 1: purpose -> model
        if purpose and not resolved_model:
            resolved_model = self.task_routes.get(purpose)
            if resolved_model:
                logger.debug(
                    "task_route_resolved", purpose=purpose, model=resolved_model
                )

        # Step 2: explicit provider
        if provider:
            prov = self._providers.get(provider)
            if prov is None:
                raise ValueError(f"Provider '{provider}' is not registered")
            if resolved_model is None:
                raise ValueError(
                    f"Cannot resolve model: provider '{provider}' specified "
                    "but no model or known purpose given"
                )
            return prov, resolved_model

        # Step 3: model -> provider via glob routes
        if resolved_model:
            provider_name = self._match_model_route(resolved_model)
            if provider_name:
                prov = self._providers.get(provider_name)
                if prov is not None:
                    return prov, resolved_model
                logger.warning(
                    "model_route_provider_missing",
                    model=resolved_model,
                    expected_provider=provider_name,
                )

        # Step 4: fallback chain
        for fb_name in self.fallback_chain:
            prov = self._providers.get(fb_name)
            if prov is not None:
                fallback_model = resolved_model or self._default_model_for(fb_name)
                if fallback_model:
                    logger.info(
                        "fallback_resolution",
                        provider=fb_name,
                        model=fallback_model,
                    )
                    return prov, fallback_model

        raise ValueError(
            f"Cannot resolve provider for model={model!r}, "
            f"provider={provider!r}, purpose={purpose!r}. "
            f"Registered providers: {self.provider_names}"
        )

    def _match_model_route(self, model: str) -> str | None:
        """Match a model identifier against glob patterns in model_routes."""
        for pattern, provider_name in self.model_routes.items():
            if fnmatch.fnmatch(model, pattern):
                return provider_name
        return None

    def _default_model_for(self, provider_name: str) -> str | None:
        """Return the first model in task_routes that maps to this provider."""
        for _purpose, model in self.task_routes.items():
            route = self._match_model_route(model)
            if route == provider_name:
                return model
        return None

    # ── Fallback ──────────────────────────────────────────────────────────

    def get_fallback(self, current_provider: str) -> LLMProvider | None:
        """Return the next provider in the fallback chain after *current_provider*.

        Args:
            current_provider: The provider that just failed.

        Returns:
            Next provider instance, or ``None`` if no fallback is available.
        """
        try:
            idx = self.fallback_chain.index(current_provider)
        except ValueError:
            # Current provider is not in the chain; try the first entry.
            idx = -1

        for name in self.fallback_chain[idx + 1 :]:
            prov = self._providers.get(name)
            if prov is not None:
                return prov
        return None

    # ── Cost estimation ───────────────────────────────────────────────────

    def estimate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate the USD cost of a request.

        Uses glob matching against the pricing table.

        Args:
            provider: Provider name.
            model: Model identifier.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.

        Returns:
            Estimated cost in USD (may be 0.0 if no pricing data).
        """
        for (p, m_pattern), (in_price, out_price) in self.pricing.items():
            if p == provider and fnmatch.fnmatch(model, m_pattern):
                return (input_tokens / 1000 * in_price) + (
                    output_tokens / 1000 * out_price
                )
        return 0.0

    # ── List all models ───────────────────────────────────────────────────

    def list_all_models(self) -> list[ModelInfo]:
        """Aggregate models from all registered providers."""
        models: list[ModelInfo] = []
        for prov in self._providers.values():
            models.extend(prov.list_models())
        return models

    # ── Factory ───────────────────────────────────────────────────────────

    def init_from_settings(self, settings: Any) -> None:
        """Configure the registry from application settings.

        Initialises providers based on which API keys are configured, sets up
        the fallback chain, and optionally overrides task/model routes.

        Args:
            settings: An object with LLM-related attributes (typically
                :class:`agentlake.config.GatewaySettings`).
        """
        from agentlake.llm_gateway.providers.anthropic import AnthropicProvider
        from agentlake.llm_gateway.providers.openai_compat import OpenAICompatProvider
        from agentlake.llm_gateway.providers.openrouter import OpenRouterProvider

        # Register providers whose keys are present.
        anthropic_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
        if anthropic_key:
            self.register_provider(AnthropicProvider(api_key=anthropic_key))

        openrouter_key = getattr(settings, "OPENROUTER_API_KEY", "") or ""
        if openrouter_key:
            self.register_provider(OpenRouterProvider(api_key=openrouter_key))

        compat_url = getattr(settings, "OPENAI_COMPAT_BASE_URL", "") or ""
        if compat_url:
            compat_key = getattr(settings, "OPENAI_COMPAT_API_KEY", "") or ""
            compat_model = getattr(settings, "OPENAI_COMPAT_DEFAULT_MODEL", "default") or "default"
            self.register_provider(
                OpenAICompatProvider(
                    base_url=compat_url,
                    api_key=compat_key,
                    default_model=compat_model,
                )
            )

        # Fallback chain from settings or sensible default.
        fallback_raw = getattr(settings, "LLM_FALLBACK_CHAIN", "") or ""
        if fallback_raw:
            self.fallback_chain = [
                s.strip() for s in fallback_raw.split(",") if s.strip()
            ]
        else:
            # Default: prefer anthropic, fall back to openrouter, then compat.
            self.fallback_chain = [
                name
                for name in ("anthropic", "openrouter", "openai_compat")
                if name in self._providers
            ]

        # Override default provider if specified.
        default_provider = getattr(settings, "LLM_DEFAULT_PROVIDER", "") or ""
        if default_provider and default_provider in self._providers:
            # Move to front of fallback chain.
            if default_provider in self.fallback_chain:
                self.fallback_chain.remove(default_provider)
            self.fallback_chain.insert(0, default_provider)

        # Override task routes from settings.
        default_model = getattr(settings, "LLM_DEFAULT_MODEL", "") or ""
        if default_model:
            # Set all task routes to the default model
            for key in self.task_routes:
                self.task_routes[key] = default_model

        # Allow per-task overrides via LLM_TASK_* env vars.
        task_map = {
            "LLM_TASK_SUMMARIZE_CHUNK": "summarize",
            "LLM_TASK_SUMMARIZE_DOCUMENT": "summarize",
            "LLM_TASK_CLASSIFY_ONTOLOGY": "classify",
            "LLM_TASK_EXTRACT_ENTITIES": "extract_entities",
            "LLM_TASK_EXTRACT_RELATIONSHIPS": "extract_relationships",
            "LLM_TASK_EMBED": "embed",
        }
        for env_key, task_name in task_map.items():
            val = getattr(settings, env_key, "") or ""
            if val:
                self.task_routes[task_name] = val

        logger.info(
            "registry_initialized",
            providers=self.provider_names,
            fallback_chain=self.fallback_chain,
            task_routes=self.task_routes,
        )

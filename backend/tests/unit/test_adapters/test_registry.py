"""Tests for the adapter registry."""

from __future__ import annotations

import pytest

from agentlake.adapters.base import ExtractedContent, TextBlock
from agentlake.adapters.registry import AdapterRegistry
from agentlake.adapters.text import TextAdapter


class _FakeAdapter:
    """Minimal adapter for testing custom registration."""

    supported_extensions = [".fake"]
    supported_mimetypes = ["application/x-fake"]

    def can_handle(self, filename: str, content_type: str) -> bool:
        return filename.endswith(".fake") or content_type == "application/x-fake"

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        return ExtractedContent(
            text_blocks=[
                TextBlock(
                    content=file_bytes.decode(),
                    block_type="paragraph",
                    position=0,
                    source_locator="fake:1",
                )
            ],
            metadata={"filename": filename},
        )


class TestAdapterRegistry:
    """Unit tests for AdapterRegistry."""

    def test_empty_registry(self) -> None:
        registry = AdapterRegistry()
        assert registry.registered_adapters == []
        assert registry.get_adapter("test.txt", "text/plain") is None

    def test_register_single_adapter(self) -> None:
        registry = AdapterRegistry()
        adapter = TextAdapter()
        registry.register(adapter)
        assert len(registry.registered_adapters) == 1

    def test_get_adapter_for_txt(self) -> None:
        registry = AdapterRegistry()
        adapter = TextAdapter()
        registry.register(adapter)
        found = registry.get_adapter("test.txt", "text/plain")
        assert found is adapter

    def test_get_adapter_returns_none_for_unknown(self) -> None:
        registry = AdapterRegistry()
        registry.register(TextAdapter())
        assert registry.get_adapter("test.xyz", "application/x-unknown") is None

    def test_register_custom_adapter(self) -> None:
        registry = AdapterRegistry()
        fake = _FakeAdapter()
        registry.register(fake)
        assert registry.get_adapter("data.fake", "application/x-fake") is fake

    def test_extract_delegates_to_correct_adapter(self) -> None:
        registry = AdapterRegistry()
        registry.register(TextAdapter())
        result = registry.extract(b"hello", "test.txt", "text/plain")
        assert len(result.text_blocks) >= 1
        assert "hello" in result.text_blocks[0].content

    def test_extract_raises_for_unknown_type(self) -> None:
        registry = AdapterRegistry()
        registry.register(TextAdapter())
        with pytest.raises(ValueError, match="No adapter found"):
            registry.extract(b"data", "test.xyz", "application/x-unknown")

    def test_auto_discover_finds_adapters(self) -> None:
        registry = AdapterRegistry()
        registry.auto_discover()
        assert len(registry.registered_adapters) > 0
        # Should find at least text and markdown adapters
        extensions = registry.supported_extensions
        assert ".txt" in extensions
        assert ".md" in extensions

    def test_auto_discover_finds_csv_adapter(self) -> None:
        registry = AdapterRegistry()
        registry.auto_discover()
        assert ".csv" in registry.supported_extensions

    def test_auto_discover_finds_json_adapter(self) -> None:
        registry = AdapterRegistry()
        registry.auto_discover()
        assert ".json" in registry.supported_extensions

    def test_supported_extensions_deduplicates(self) -> None:
        registry = AdapterRegistry()
        registry.register(TextAdapter())
        registry.register(TextAdapter())
        # Even with duplicate registrations, extensions list is deduplicated
        extensions = registry.supported_extensions
        assert extensions.count(".txt") == 1

    def test_first_matching_adapter_wins(self) -> None:
        """When two adapters can handle the same file, the first registered wins."""
        registry = AdapterRegistry()
        first = TextAdapter()
        second = TextAdapter()
        registry.register(first)
        registry.register(second)
        found = registry.get_adapter("test.txt", "text/plain")
        assert found is first

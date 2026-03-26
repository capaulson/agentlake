"""Tests for the JSON/YAML/XML file adapter."""

from __future__ import annotations

import pytest

from agentlake.adapters.json_adapter import JsonYamlAdapter


class TestJsonYamlAdapter:
    """Unit tests for the JsonYamlAdapter."""

    def setup_method(self) -> None:
        self.adapter = JsonYamlAdapter()

    # ── can_handle ────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        ("filename", "content_type"),
        [
            ("data.json", "application/json"),
            ("config.yaml", "application/yaml"),
            ("config.yml", "text/yaml"),
            ("data.xml", "text/xml"),
            ("data.xml", "application/xml"),
        ],
    )
    def test_can_handle(self, filename: str, content_type: str) -> None:
        assert self.adapter.can_handle(filename, content_type)

    def test_cannot_handle_csv(self) -> None:
        assert not self.adapter.can_handle("data.csv", "text/csv")

    # ── JSON extraction ──────────────────────────────────────────────────

    def test_json_simple_object(self) -> None:
        content = b'{"name": "Alice", "age": 30}'
        result = self.adapter.extract(content, "test.json")
        assert len(result.text_blocks) == 2
        assert result.metadata["format"] == "json"

    def test_json_key_path_locators(self) -> None:
        content = b'{"name": "Alice"}'
        result = self.adapter.extract(content, "test.json")
        assert result.text_blocks[0].source_locator == "key:$.name"

    def test_json_nested_object(self) -> None:
        content = b'{"config": {"max_tokens": 1024}}'
        result = self.adapter.extract(content, "test.json")
        assert any("$.config.max_tokens" in b.source_locator for b in result.text_blocks)

    def test_json_array(self) -> None:
        content = b'{"items": ["a", "b", "c"]}'
        result = self.adapter.extract(content, "test.json")
        assert any("$.items[0]" in b.source_locator for b in result.text_blocks)

    def test_json_invalid_returns_raw(self) -> None:
        content = b"this is not json"
        result = self.adapter.extract(content, "test.json")
        assert len(result.text_blocks) == 1
        assert result.metadata.get("parse_error") is True

    def test_json_empty_object(self) -> None:
        content = b"{}"
        result = self.adapter.extract(content, "test.json")
        assert len(result.text_blocks) == 0

    # ── YAML extraction ──────────────────────────────────────────────────

    def test_yaml_simple(self) -> None:
        content = b"name: Alice\nage: 30"
        result = self.adapter.extract(content, "test.yaml")
        assert len(result.text_blocks) == 2
        assert result.metadata["format"] == "yaml"

    def test_yaml_nested(self) -> None:
        content = b"config:\n  max_tokens: 1024\n  overlap: 64"
        result = self.adapter.extract(content, "test.yaml")
        assert any("max_tokens" in b.source_locator for b in result.text_blocks)

    def test_yaml_empty(self) -> None:
        content = b""
        result = self.adapter.extract(content, "test.yaml")
        # Empty YAML results in None -> empty dict -> 0 blocks
        assert len(result.text_blocks) == 0

    def test_yaml_invalid_handled_gracefully(self) -> None:
        content = b"invalid: [unclosed yaml"
        result = self.adapter.extract(content, "bad.yaml")
        # Should not crash
        assert len(result.text_blocks) >= 0

    # ── XML extraction ───────────────────────────────────────────────────

    def test_xml_simple(self) -> None:
        content = b"<root><name>Alice</name><age>30</age></root>"
        result = self.adapter.extract(content, "test.xml")
        assert len(result.text_blocks) == 2
        assert result.metadata["format"] == "xml"
        assert result.metadata["root_tag"] == "root"

    def test_xml_key_path_locators(self) -> None:
        content = b"<root><name>Alice</name></root>"
        result = self.adapter.extract(content, "test.xml")
        assert result.text_blocks[0].source_locator == "key:$/root/name"

    def test_xml_invalid_returns_raw(self) -> None:
        content = b"<unclosed>"
        result = self.adapter.extract(content, "test.xml")
        assert len(result.text_blocks) == 1
        assert result.metadata.get("parse_error") is True

    def test_xml_nested(self) -> None:
        content = b"<root><parent><child>value</child></parent></root>"
        result = self.adapter.extract(content, "test.xml")
        assert any("child" in b.source_locator for b in result.text_blocks)

    # ── Fixture file ──────────────────────────────────────────────────────

    def test_fixture_json_file(self) -> None:
        import pathlib

        fixture = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "sample.json"
        content = fixture.read_bytes()
        result = self.adapter.extract(content, "sample.json")
        assert len(result.text_blocks) > 0
        assert result.metadata["format"] == "json"
        # Should find the "project" key
        assert any("project" in b.source_locator for b in result.text_blocks)

    def test_block_positions_sequential(self) -> None:
        content = b'{"a": 1, "b": 2, "c": 3}'
        result = self.adapter.extract(content, "test.json")
        positions = [b.position for b in result.text_blocks]
        assert positions == sorted(positions)

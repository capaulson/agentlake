"""Tests for text file adapter."""

from __future__ import annotations

import pytest

from agentlake.adapters.text import TextAdapter


class TestTextAdapter:
    """Unit tests for the plain-text adapter."""

    def setup_method(self) -> None:
        self.adapter = TextAdapter()

    # ── can_handle ────────────────────────────────────────────────────────

    def test_can_handle_txt(self) -> None:
        assert self.adapter.can_handle("test.txt", "text/plain")

    def test_can_handle_txt_uppercase(self) -> None:
        assert self.adapter.can_handle("README.TXT", "application/octet-stream")

    def test_can_handle_by_mimetype(self) -> None:
        assert self.adapter.can_handle("unknown_ext", "text/plain")

    def test_cannot_handle_pdf(self) -> None:
        assert not self.adapter.can_handle("test.pdf", "application/pdf")

    def test_cannot_handle_csv(self) -> None:
        assert not self.adapter.can_handle("data.csv", "text/csv")

    # ── extract ───────────────────────────────────────────────────────────

    def test_extract_simple_text(self) -> None:
        content = b"Hello world\n\nSecond paragraph"
        result = self.adapter.extract(content, "test.txt")
        assert len(result.text_blocks) == 2
        assert "Hello world" in result.text_blocks[0].content
        assert "Second paragraph" in result.text_blocks[1].content

    def test_extract_single_paragraph(self) -> None:
        content = b"Just one paragraph with no blank lines."
        result = self.adapter.extract(content, "test.txt")
        assert len(result.text_blocks) == 1
        assert result.text_blocks[0].content == "Just one paragraph with no blank lines."

    def test_extract_multiple_paragraphs(self) -> None:
        content = b"Para one\n\nPara two\n\nPara three"
        result = self.adapter.extract(content, "test.txt")
        assert len(result.text_blocks) == 3

    def test_extract_empty(self) -> None:
        result = self.adapter.extract(b"", "empty.txt")
        assert len(result.text_blocks) == 0

    def test_extract_only_whitespace(self) -> None:
        result = self.adapter.extract(b"   \n\n   \n", "blank.txt")
        assert len(result.text_blocks) == 0

    def test_source_locators_are_present(self) -> None:
        content = b"Line one\n\nLine two"
        result = self.adapter.extract(content, "test.txt")
        for block in result.text_blocks:
            assert block.source_locator.startswith("line:")

    def test_source_locator_line_numbers(self) -> None:
        content = b"First paragraph\n\nSecond paragraph"
        result = self.adapter.extract(content, "test.txt")
        assert result.text_blocks[0].source_locator == "line:1"
        assert result.text_blocks[1].source_locator == "line:3"

    def test_block_type_is_paragraph(self) -> None:
        content = b"Some text\n\nMore text"
        result = self.adapter.extract(content, "test.txt")
        for block in result.text_blocks:
            assert block.block_type == "paragraph"

    def test_sequential_positions(self) -> None:
        content = b"A\n\nB\n\nC"
        result = self.adapter.extract(content, "test.txt")
        positions = [b.position for b in result.text_blocks]
        assert positions == [0, 1, 2]

    def test_metadata_contains_filename(self) -> None:
        result = self.adapter.extract(b"hi", "my_file.txt")
        assert result.metadata["filename"] == "my_file.txt"

    def test_utf8_content(self) -> None:
        content = "Caf\u00e9 na\u00efve r\u00e9sum\u00e9".encode("utf-8")
        result = self.adapter.extract(content, "unicode.txt")
        assert len(result.text_blocks) == 1
        assert "Caf\u00e9" in result.text_blocks[0].content

    def test_full_text_property(self) -> None:
        content = b"Alpha\n\nBeta"
        result = self.adapter.extract(content, "test.txt")
        assert "Alpha" in result.full_text
        assert "Beta" in result.full_text

    def test_extract_from_fixture_file(self) -> None:
        import pathlib

        fixture = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "sample.txt"
        content = fixture.read_bytes()
        result = self.adapter.extract(content, "sample.txt")
        assert len(result.text_blocks) >= 2
        assert "AgentLake" in result.text_blocks[0].content

    def test_multiple_blank_lines(self) -> None:
        content = b"First\n\n\n\nSecond"
        result = self.adapter.extract(content, "test.txt")
        assert len(result.text_blocks) == 2

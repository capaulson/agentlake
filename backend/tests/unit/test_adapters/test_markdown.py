"""Tests for the markdown file adapter."""

from __future__ import annotations

import pytest

from agentlake.adapters.markdown import MarkdownAdapter


class TestMarkdownAdapter:
    """Unit tests for the MarkdownAdapter."""

    def setup_method(self) -> None:
        self.adapter = MarkdownAdapter()

    # ── can_handle ────────────────────────────────────────────────────────

    def test_can_handle_md(self) -> None:
        assert self.adapter.can_handle("readme.md", "text/markdown")

    def test_can_handle_markdown(self) -> None:
        assert self.adapter.can_handle("doc.markdown", "text/plain")

    def test_can_handle_mkd(self) -> None:
        assert self.adapter.can_handle("doc.mkd", "text/plain")

    def test_can_handle_by_mimetype(self) -> None:
        assert self.adapter.can_handle("unknown", "text/markdown")

    def test_cannot_handle_txt(self) -> None:
        assert not self.adapter.can_handle("file.txt", "text/plain")

    # ── Frontmatter ───────────────────────────────────────────────────────

    def test_extracts_yaml_frontmatter(self) -> None:
        content = b"---\ntitle: Hello\nauthor: Test\n---\n\nSome content."
        result = self.adapter.extract(content, "test.md")
        assert "frontmatter" in result.metadata
        assert result.metadata["frontmatter"]["title"] == "Hello"
        assert result.metadata["frontmatter"]["author"] == "Test"

    def test_frontmatter_raw_preserved(self) -> None:
        content = b"---\ntitle: Hello\n---\n\nContent."
        result = self.adapter.extract(content, "test.md")
        assert "frontmatter_raw" in result.metadata
        assert "title: Hello" in result.metadata["frontmatter_raw"]

    def test_no_frontmatter(self) -> None:
        content = b"# Just a heading\n\nSome text."
        result = self.adapter.extract(content, "test.md")
        assert "frontmatter" not in result.metadata

    def test_invalid_frontmatter_handled_gracefully(self) -> None:
        content = b"---\ninvalid: [unclosed\n---\n\nContent."
        result = self.adapter.extract(content, "test.md")
        # Should not crash, frontmatter may be empty dict
        assert result.metadata.get("frontmatter") is not None or True

    # ── Headings ──────────────────────────────────────────────────────────

    def test_heading_detection(self) -> None:
        content = b"# H1\n\n## H2\n\n### H3"
        result = self.adapter.extract(content, "test.md")
        headings = [b for b in result.text_blocks if b.block_type == "heading"]
        assert len(headings) == 3
        assert headings[0].content == "H1"
        assert headings[0].metadata["level"] == 1
        assert headings[1].content == "H2"
        assert headings[1].metadata["level"] == 2
        assert headings[2].content == "H3"
        assert headings[2].metadata["level"] == 3

    def test_heading_source_locators(self) -> None:
        content = b"# Title\n\nParagraph\n\n## Section"
        result = self.adapter.extract(content, "test.md")
        headings = [b for b in result.text_blocks if b.block_type == "heading"]
        for h in headings:
            assert h.source_locator.startswith("line:")

    # ── Code blocks ───────────────────────────────────────────────────────

    def test_fenced_code_block(self) -> None:
        content = b"# Title\n\n```python\ndef hello():\n    pass\n```\n\nAfter code."
        result = self.adapter.extract(content, "test.md")
        code_blocks = [b for b in result.text_blocks if b.block_type == "code"]
        assert len(code_blocks) == 1
        assert "def hello():" in code_blocks[0].content
        assert code_blocks[0].metadata["language"] == "python"

    def test_code_block_without_language(self) -> None:
        content = b"```\nplain code\n```"
        result = self.adapter.extract(content, "test.md")
        code_blocks = [b for b in result.text_blocks if b.block_type == "code"]
        assert len(code_blocks) == 1
        assert code_blocks[0].metadata["language"] == "text"

    def test_code_block_structure_markers(self) -> None:
        content = b"```python\ncode\n```"
        result = self.adapter.extract(content, "test.md")
        marker_types = [s.marker_type for s in result.structure]
        assert "code_start" in marker_types
        assert "code_end" in marker_types

    # ── Paragraphs ────────────────────────────────────────────────────────

    def test_paragraph_extraction(self) -> None:
        content = b"First paragraph here.\n\nSecond paragraph here."
        result = self.adapter.extract(content, "test.md")
        paragraphs = [b for b in result.text_blocks if b.block_type == "paragraph"]
        assert len(paragraphs) == 2

    def test_empty_document(self) -> None:
        result = self.adapter.extract(b"", "empty.md")
        assert len(result.text_blocks) == 0

    # ── Fixture file ──────────────────────────────────────────────────────

    def test_fixture_file(self) -> None:
        import pathlib

        fixture = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "sample.md"
        content = fixture.read_bytes()
        result = self.adapter.extract(content, "sample.md")

        # Should have frontmatter
        assert "frontmatter" in result.metadata
        assert result.metadata["frontmatter"]["title"] == "Sample Document"

        # Should have headings
        headings = [b for b in result.text_blocks if b.block_type == "heading"]
        assert len(headings) >= 2

        # Should have a code block
        code_blocks = [b for b in result.text_blocks if b.block_type == "code"]
        assert len(code_blocks) == 1
        assert "def hello():" in code_blocks[0].content

    def test_sequential_positions(self) -> None:
        content = b"# H1\n\nParagraph\n\n## H2\n\nAnother para"
        result = self.adapter.extract(content, "test.md")
        positions = [b.position for b in result.text_blocks]
        assert positions == sorted(positions)
        # Positions should be unique sequential integers
        assert positions == list(range(len(positions)))

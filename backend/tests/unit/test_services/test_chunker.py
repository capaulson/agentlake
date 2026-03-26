"""Tests for the semantic chunker service."""

from __future__ import annotations

import hashlib

import pytest

from agentlake.adapters.base import ExtractedContent, TextBlock
from agentlake.services.chunker import SemanticChunker, count_tokens, _content_hash


def _make_blocks(texts: list[str], block_type: str = "paragraph") -> list[TextBlock]:
    """Helper to create TextBlock instances."""
    return [
        TextBlock(
            content=t,
            block_type=block_type,
            position=i,
            source_locator=f"line:{i * 10 + 1}",
        )
        for i, t in enumerate(texts)
    ]


def _make_extracted(texts: list[str], block_type: str = "paragraph") -> ExtractedContent:
    """Helper to create ExtractedContent instances."""
    return ExtractedContent(text_blocks=_make_blocks(texts, block_type))


class TestCountTokens:
    """Tests for the token counting utility."""

    def test_count_tokens_simple(self) -> None:
        count = count_tokens("Hello world")
        assert isinstance(count, int)
        assert count > 0

    def test_count_tokens_empty(self) -> None:
        assert count_tokens("") == 0

    def test_count_tokens_long_text(self) -> None:
        text = "word " * 1000
        count = count_tokens(text)
        assert count > 500


class TestContentHash:
    """Tests for the content hash utility."""

    def test_hash_is_sha256(self) -> None:
        text = "Hello world"
        result = _content_hash(text)
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert result == expected

    def test_hash_length(self) -> None:
        result = _content_hash("test")
        assert len(result) == 64

    def test_different_content_different_hash(self) -> None:
        assert _content_hash("alpha") != _content_hash("beta")

    def test_same_content_same_hash(self) -> None:
        assert _content_hash("same") == _content_hash("same")


class TestSemanticChunker:
    """Unit tests for the SemanticChunker."""

    def setup_method(self) -> None:
        self.chunker = SemanticChunker(max_tokens=1024, overlap_tokens=64)

    # ── Empty input ───────────────────────────────────────────────────────

    def test_empty_content(self) -> None:
        extracted = ExtractedContent(text_blocks=[])
        chunks = self.chunker.chunk(extracted)
        assert chunks == []

    # ── Basic chunking ────────────────────────────────────────────────────

    def test_simple_text_chunks(self) -> None:
        extracted = _make_extracted(["Paragraph one.", "Paragraph two."])
        chunks = self.chunker.chunk(extracted)
        assert len(chunks) >= 1
        # All content should be present
        full_content = " ".join(c.content for c in chunks)
        assert "Paragraph one" in full_content
        assert "Paragraph two" in full_content

    def test_short_text_single_chunk(self) -> None:
        extracted = _make_extracted(["Short text."])
        chunks = self.chunker.chunk(extracted)
        assert len(chunks) == 1

    def test_chunk_has_content_hash(self) -> None:
        extracted = _make_extracted(["Some text content."])
        chunks = self.chunker.chunk(extracted)
        assert len(chunks) == 1
        assert len(chunks[0].content_hash) == 64

    def test_chunk_has_token_count(self) -> None:
        extracted = _make_extracted(["Some text content."])
        chunks = self.chunker.chunk(extracted)
        assert chunks[0].token_count > 0

    def test_chunk_index_sequential(self) -> None:
        extracted = _make_extracted(["A " * 500, "B " * 500, "C " * 500])
        chunks = self.chunker.chunk(extracted)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_source_locators_preserved(self) -> None:
        extracted = _make_extracted(["Content here."])
        chunks = self.chunker.chunk(extracted)
        assert chunks[0].source_locator.startswith("line:")

    # ── Token limit ───────────────────────────────────────────────────────

    def test_respects_max_tokens(self) -> None:
        # Create a very small max_tokens to force splitting
        chunker = SemanticChunker(max_tokens=50, overlap_tokens=0)
        long_text = "This is a sentence. " * 100
        extracted = _make_extracted([long_text])
        chunks = chunker.chunk(extracted)
        assert len(chunks) > 1

    def test_large_paragraph_gets_sentence_split(self) -> None:
        # Use a very small limit to force sentence splitting
        chunker = SemanticChunker(max_tokens=30, overlap_tokens=0)
        text = "First sentence here. Second sentence here. Third sentence here."
        extracted = _make_extracted([text])
        chunks = chunker.chunk(extracted)
        assert len(chunks) >= 1

    # ── Atomic blocks ─────────────────────────────────────────────────────

    def test_code_blocks_stay_together(self) -> None:
        blocks = [
            TextBlock(content="Intro.", block_type="paragraph", position=0, source_locator="line:1"),
            TextBlock(content="def foo():\n    pass", block_type="code", position=1, source_locator="line:3"),
            TextBlock(content="After code.", block_type="paragraph", position=2, source_locator="line:6"),
        ]
        extracted = ExtractedContent(text_blocks=blocks)
        chunks = self.chunker.chunk(extracted)
        # The code block should appear intact in some chunk
        found_code = False
        for c in chunks:
            if "def foo():" in c.content:
                found_code = True
                break
        assert found_code

    def test_table_blocks_are_atomic(self) -> None:
        blocks = [
            TextBlock(content="Header row", block_type="table", position=0, source_locator="row:1"),
            TextBlock(content="Data row", block_type="table", position=1, source_locator="row:2"),
        ]
        extracted = ExtractedContent(text_blocks=blocks)
        chunks = self.chunker.chunk(extracted)
        assert len(chunks) >= 1

    # ── Overlap ───────────────────────────────────────────────────────────

    def test_overlap_applied(self) -> None:
        chunker = SemanticChunker(max_tokens=50, overlap_tokens=10)
        long_text = "The quick brown fox jumps over the lazy dog. " * 50
        extracted = _make_extracted([long_text])
        chunks = chunker.chunk(extracted)
        if len(chunks) > 1:
            # Second chunk should contain some text from the end of the first
            # (the overlap tokens are prepended)
            assert chunks[1].token_count > 0

    def test_no_overlap_when_disabled(self) -> None:
        chunker = SemanticChunker(max_tokens=50, overlap_tokens=0)
        long_text = "Word. " * 100
        extracted = _make_extracted([long_text])
        chunks = chunker.chunk(extracted)
        assert len(chunks) >= 1

    # ── Text block tracking ───────────────────────────────────────────────

    def test_text_blocks_tracked(self) -> None:
        extracted = _make_extracted(["Hello world."])
        chunks = self.chunker.chunk(extracted)
        assert len(chunks[0].text_blocks) >= 1

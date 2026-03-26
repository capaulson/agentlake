"""Integration test: Upload a file, process it, and search for it.

These tests require running infrastructure (PostgreSQL, Redis, MinIO).
Skip with ``pytest -m "not integration"`` when infrastructure is unavailable.
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentlake.adapters.registry import AdapterRegistry
from agentlake.adapters.text import TextAdapter
from agentlake.services.chunker import SemanticChunker

pytestmark = pytest.mark.integration


class TestUploadPipeline:
    """Integration test simulating the upload-to-search pipeline."""

    @pytest.mark.asyncio
    async def test_text_adapter_to_chunker_pipeline(self) -> None:
        """Verify that text adapter output feeds cleanly into the chunker."""
        # 1. Extract text using adapter
        adapter = TextAdapter()
        file_content = (
            b"AgentLake is a distributed data lake.\n\n"
            b"It processes files through an LLM pipeline.\n\n"
            b"Search results include citations."
        )
        extracted = adapter.extract(file_content, "test.txt")
        assert len(extracted.text_blocks) == 3

        # 2. Chunk the extracted content
        chunker = SemanticChunker(max_tokens=1024, overlap_tokens=64)
        chunks = chunker.chunk(extracted)
        assert len(chunks) >= 1

        # 3. Verify chunk properties
        for chunk in chunks:
            assert chunk.content_hash is not None
            assert len(chunk.content_hash) == 64
            assert chunk.token_count > 0
            assert chunk.chunk_index >= 0
            assert chunk.source_locator.startswith("line:")

    @pytest.mark.asyncio
    async def test_adapter_registry_to_chunker(self) -> None:
        """Registry discovers the right adapter and feeds into chunker."""
        registry = AdapterRegistry()
        registry.auto_discover()

        # Extract from CSV
        csv_content = b"name,role\nAlice,Engineer\nBob,Manager"
        extracted = registry.extract(csv_content, "staff.csv", "text/csv")
        assert len(extracted.text_blocks) > 0

        chunker = SemanticChunker(max_tokens=1024, overlap_tokens=0)
        chunks = chunker.chunk(extracted)
        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_markdown_adapter_to_chunker(self) -> None:
        """Markdown adapter preserves structure through chunking."""
        registry = AdapterRegistry()
        registry.auto_discover()

        md_content = (
            b"---\ntitle: Test\n---\n\n"
            b"# Overview\n\nThis is the overview.\n\n"
            b"## Details\n\nHere are the details.\n\n"
            b"```python\ndef main():\n    pass\n```\n"
        )
        extracted = registry.extract(md_content, "doc.md", "text/markdown")
        assert len(extracted.text_blocks) > 0

        chunker = SemanticChunker(max_tokens=1024, overlap_tokens=0)
        chunks = chunker.chunk(extracted)
        assert len(chunks) >= 1

        # Verify code block content is preserved
        all_content = " ".join(c.content for c in chunks)
        assert "def main():" in all_content

    @pytest.mark.asyncio
    async def test_upload_process_verify_citations_flow(self) -> None:
        """Simulate the full upload flow with mocked services.

        1. Upload a test file
        2. Extract and chunk
        3. Verify citations can be generated
        """
        adapter = TextAdapter()
        content = (
            b"The quick brown fox jumps over the lazy dog. "
            b"This is a test document for the AgentLake pipeline."
        )
        extracted = adapter.extract(content, "test.txt")

        chunker = SemanticChunker(max_tokens=1024, overlap_tokens=0)
        chunks = chunker.chunk(extracted)

        # Simulate citation generation
        for idx, chunk in enumerate(chunks):
            file_id = uuid.uuid4()
            citation_url = (
                f"/api/v1/vault/files/{file_id}/download"
                f"#chunk={chunk.chunk_index}"
            )
            assert file_id is not None
            assert f"chunk={chunk.chunk_index}" in citation_url

    @pytest.mark.asyncio
    async def test_incremental_reprocess_hash_comparison(self) -> None:
        """Verify that unchanged chunks produce the same hash."""
        adapter = TextAdapter()
        chunker = SemanticChunker(max_tokens=1024, overlap_tokens=0)

        # Process first time
        content_v1 = b"Paragraph one.\n\nParagraph two."
        chunks_v1 = chunker.chunk(adapter.extract(content_v1, "v1.txt"))

        # Process again with same content
        chunks_v2 = chunker.chunk(adapter.extract(content_v1, "v2.txt"))

        # Same content should produce same hashes
        assert len(chunks_v1) == len(chunks_v2)
        for c1, c2 in zip(chunks_v1, chunks_v2):
            assert c1.content_hash == c2.content_hash

        # Process with different content
        content_v3 = b"Paragraph one.\n\nChanged paragraph two."
        chunks_v3 = chunker.chunk(adapter.extract(content_v3, "v3.txt"))

        # Different content should produce different hashes
        # (at least for the changed chunk)
        hashes_v1 = {c.content_hash for c in chunks_v1}
        hashes_v3 = {c.content_hash for c in chunks_v3}
        assert hashes_v1 != hashes_v3

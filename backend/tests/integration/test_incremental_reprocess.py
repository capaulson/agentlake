"""Integration tests for incremental reprocessing.

Verifies that when a file is re-uploaded with small changes, only
the changed chunks are re-processed (identified by content hash).
"""

from __future__ import annotations

import pytest

from agentlake.adapters.text import TextAdapter
from agentlake.services.chunker import SemanticChunker

pytestmark = pytest.mark.integration


class TestIncrementalReprocess:
    """Integration tests for incremental reprocessing logic."""

    def setup_method(self) -> None:
        self.adapter = TextAdapter()
        self.chunker = SemanticChunker(max_tokens=100, overlap_tokens=0)

    def test_unchanged_file_produces_same_hashes(self) -> None:
        """Re-processing an identical file produces identical chunk hashes."""
        content = b"First paragraph.\n\nSecond paragraph.\n\nThird paragraph."

        chunks_v1 = self.chunker.chunk(self.adapter.extract(content, "v1.txt"))
        chunks_v2 = self.chunker.chunk(self.adapter.extract(content, "v2.txt"))

        assert len(chunks_v1) == len(chunks_v2)
        for c1, c2 in zip(chunks_v1, chunks_v2):
            assert c1.content_hash == c2.content_hash

    def test_small_change_affects_only_changed_chunk(self) -> None:
        """Changing one paragraph should only affect the chunk containing it."""
        original = b"Paragraph A is about dogs.\n\nParagraph B is about cats."
        modified = b"Paragraph A is about dogs.\n\nParagraph B is about birds."

        chunks_orig = self.chunker.chunk(self.adapter.extract(original, "orig.txt"))
        chunks_mod = self.chunker.chunk(self.adapter.extract(modified, "mod.txt"))

        assert len(chunks_orig) == len(chunks_mod)

        # Count how many chunks changed
        changed = 0
        unchanged = 0
        for c1, c2 in zip(chunks_orig, chunks_mod):
            if c1.content_hash == c2.content_hash:
                unchanged += 1
            else:
                changed += 1

        # At least one should be unchanged, at least one should change
        assert unchanged >= 1, "Expected at least one unchanged chunk"
        assert changed >= 1, "Expected at least one changed chunk"

    def test_adding_paragraph_changes_hash_set(self) -> None:
        """Adding a new paragraph produces a new chunk hash not in the original set."""
        original = b"Paragraph one.\n\nParagraph two."
        expanded = b"Paragraph one.\n\nParagraph two.\n\nParagraph three."

        chunks_orig = self.chunker.chunk(self.adapter.extract(original, "orig.txt"))
        chunks_exp = self.chunker.chunk(self.adapter.extract(expanded, "exp.txt"))

        orig_hashes = {c.content_hash for c in chunks_orig}
        exp_hashes = {c.content_hash for c in chunks_exp}

        # The expanded version should have at least one new hash
        new_hashes = exp_hashes - orig_hashes
        assert len(new_hashes) >= 1

    def test_removing_paragraph_reduces_chunks(self) -> None:
        """Removing a paragraph may reduce the number of chunks."""
        original = b"Para A.\n\nPara B.\n\nPara C.\n\nPara D."
        reduced = b"Para A.\n\nPara C.\n\nPara D."

        chunks_orig = self.chunker.chunk(self.adapter.extract(original, "orig.txt"))
        chunks_red = self.chunker.chunk(self.adapter.extract(reduced, "red.txt"))

        orig_hashes = {c.content_hash for c in chunks_orig}
        red_hashes = {c.content_hash for c in chunks_red}

        # Removed chunk hash should not appear
        removed_hashes = orig_hashes - red_hashes
        assert len(removed_hashes) >= 1

    def test_delta_metadata_computation(self) -> None:
        """Compute delta stats for an incremental reprocess operation."""
        original = b"Chunk A.\n\nChunk B.\n\nChunk C."
        modified = b"Chunk A.\n\nChunk B Modified.\n\nChunk C.\n\nChunk D."

        chunks_orig = self.chunker.chunk(self.adapter.extract(original, "orig.txt"))
        chunks_mod = self.chunker.chunk(self.adapter.extract(modified, "mod.txt"))

        orig_hashes = {c.content_hash for c in chunks_orig}
        mod_hashes = {c.content_hash for c in chunks_mod}

        unchanged = orig_hashes & mod_hashes
        removed = orig_hashes - mod_hashes
        added = mod_hashes - orig_hashes

        delta = {
            "unchanged_chunks": len(unchanged),
            "removed_chunks": len(removed),
            "added_chunks": len(added),
            "total_original": len(chunks_orig),
            "total_modified": len(chunks_mod),
        }

        assert delta["total_original"] >= 1
        assert delta["total_modified"] >= 1
        assert (
            delta["unchanged_chunks"]
            + delta["removed_chunks"]
            == delta["total_original"]
        )

    def test_reorder_paragraphs_changes_hashes(self) -> None:
        """Reordering paragraphs changes chunk hashes due to overlap/position."""
        content_a = b"First paragraph.\n\nSecond paragraph."
        content_b = b"Second paragraph.\n\nFirst paragraph."

        chunks_a = self.chunker.chunk(self.adapter.extract(content_a, "a.txt"))
        chunks_b = self.chunker.chunk(self.adapter.extract(content_b, "b.txt"))

        hashes_a = {c.content_hash for c in chunks_a}
        hashes_b = {c.content_hash for c in chunks_b}

        # Different ordering should produce different hashes
        assert hashes_a != hashes_b

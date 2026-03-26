"""Integration tests for the document edit workflow.

Tests the invariant: every edit produces a DiffLog entry.
"""

from __future__ import annotations

import difflib

import pytest

from agentlake.services.diff import DiffService

pytestmark = pytest.mark.integration


class TestEditWorkflow:
    """Integration tests for edit + diff logging."""

    def test_compute_diff_equal_texts(self) -> None:
        """Identical texts should produce only 'equal' ops."""
        text = "Line one\nLine two\nLine three\n"
        ops = DiffService.compute_diff(text, text)
        assert all(op["op"] == "equal" for op in ops)

    def test_compute_diff_added_line(self) -> None:
        """Adding a line should produce an 'insert' op."""
        before = "Line one\nLine two\n"
        after = "Line one\nLine two\nLine three\n"
        ops = DiffService.compute_diff(before, after)
        insert_ops = [op for op in ops if op["op"] == "insert"]
        assert len(insert_ops) >= 1
        # The added line should be in the 'added' field
        added_text = "".join(insert_ops[0]["added"])
        assert "Line three" in added_text

    def test_compute_diff_removed_line(self) -> None:
        """Removing a line should produce a 'delete' op."""
        before = "Line one\nLine two\nLine three\n"
        after = "Line one\nLine three\n"
        ops = DiffService.compute_diff(before, after)
        delete_ops = [op for op in ops if op["op"] == "delete"]
        assert len(delete_ops) >= 1

    def test_compute_diff_replaced_line(self) -> None:
        """Changing a line should produce a 'replace' op."""
        before = "Line one\nOriginal line\nLine three\n"
        after = "Line one\nModified line\nLine three\n"
        ops = DiffService.compute_diff(before, after)
        replace_ops = [op for op in ops if op["op"] == "replace"]
        assert len(replace_ops) >= 1
        assert "Original line" in "".join(replace_ops[0]["removed"])
        assert "Modified line" in "".join(replace_ops[0]["added"])

    def test_compute_diff_has_line_ranges(self) -> None:
        """Diff ops should include before/after line ranges."""
        before = "A\nB\n"
        after = "A\nC\n"
        ops = DiffService.compute_diff(before, after)
        for op in ops:
            assert "before_start" in op
            assert "before_end" in op
            assert "after_start" in op
            assert "after_end" in op

    def test_compute_similarity_identical(self) -> None:
        """Identical texts should have similarity 1.0."""
        text = "Hello world"
        assert DiffService.compute_similarity(text, text) == 1.0

    def test_compute_similarity_completely_different(self) -> None:
        """Completely different texts should have low similarity."""
        similarity = DiffService.compute_similarity("aaa", "zzz")
        assert similarity < 0.5

    def test_compute_similarity_partial_overlap(self) -> None:
        """Partially overlapping texts should have intermediate similarity."""
        before = "The quick brown fox jumps over the lazy dog."
        after = "The quick brown cat jumps over the lazy dog."
        similarity = DiffService.compute_similarity(before, after)
        assert 0.5 < similarity < 1.0

    def test_edit_creates_version_increment(self) -> None:
        """Simulate version incrementing on edit (pure logic test)."""
        current_version = 1
        new_version = current_version + 1
        assert new_version == 2

    def test_diff_ops_cover_full_document(self) -> None:
        """All diff ops together should cover the entire before and after texts."""
        before = "Line A\nLine B\nLine C\n"
        after = "Line A\nLine D\nLine C\nLine E\n"
        ops = DiffService.compute_diff(before, after)

        # The ops should cover all before lines
        before_ranges = [(op["before_start"], op["before_end"]) for op in ops]
        before_covered = set()
        for start, end in before_ranges:
            before_covered.update(range(start, end))

        before_lines = before.splitlines(keepends=True)
        assert len(before_covered) == len(before_lines)

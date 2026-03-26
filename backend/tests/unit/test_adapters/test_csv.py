"""Tests for the CSV/TSV file adapter."""

from __future__ import annotations

import pytest

from agentlake.adapters.csv_adapter import CsvAdapter


class TestCsvAdapter:
    """Unit tests for the CsvAdapter."""

    def setup_method(self) -> None:
        self.adapter = CsvAdapter()

    # ── can_handle ────────────────────────────────────────────────────────

    def test_can_handle_csv(self) -> None:
        assert self.adapter.can_handle("data.csv", "text/csv")

    def test_can_handle_tsv(self) -> None:
        assert self.adapter.can_handle("data.tsv", "text/tab-separated-values")

    def test_can_handle_csv_by_extension(self) -> None:
        assert self.adapter.can_handle("data.csv", "application/octet-stream")

    def test_cannot_handle_txt(self) -> None:
        assert not self.adapter.can_handle("data.txt", "text/plain")

    # ── CSV parsing ───────────────────────────────────────────────────────

    def test_csv_basic_parsing(self) -> None:
        content = b"name,age\nAlice,30\nBob,25"
        result = self.adapter.extract(content, "test.csv")
        # Header + 2 data rows = 3 blocks
        assert len(result.text_blocks) == 3

    def test_csv_header_row_format(self) -> None:
        content = b"name,age\nAlice,30"
        result = self.adapter.extract(content, "test.csv")
        # First row is header, formatted as pipe-separated
        assert "name" in result.text_blocks[0].content
        assert "age" in result.text_blocks[0].content

    def test_csv_data_row_format(self) -> None:
        content = b"name,age\nAlice,30"
        result = self.adapter.extract(content, "test.csv")
        # Data rows should use "header: value" format
        data_row = result.text_blocks[1].content
        assert "name: Alice" in data_row
        assert "age: 30" in data_row

    def test_csv_row_locators(self) -> None:
        content = b"name,age\nAlice,30\nBob,25"
        result = self.adapter.extract(content, "test.csv")
        assert result.text_blocks[0].source_locator == "row:1"
        assert result.text_blocks[1].source_locator == "row:2"
        assert result.text_blocks[2].source_locator == "row:3"

    def test_csv_block_type_is_table(self) -> None:
        content = b"a,b\n1,2"
        result = self.adapter.extract(content, "test.csv")
        for block in result.text_blocks:
            assert block.block_type == "table"

    def test_csv_metadata(self) -> None:
        content = b"name,age\nAlice,30"
        result = self.adapter.extract(content, "test.csv")
        assert result.metadata["delimiter"] == ","
        assert result.metadata["columns"] == ["name", "age"]
        assert result.metadata["row_count"] == 2

    def test_csv_empty_rows_skipped(self) -> None:
        content = b"a,b\n1,2\n,,\n3,4"
        result = self.adapter.extract(content, "test.csv")
        # Empty row should be skipped
        assert len(result.text_blocks) == 3

    def test_csv_empty_file(self) -> None:
        result = self.adapter.extract(b"", "empty.csv")
        assert len(result.text_blocks) == 0

    # ── TSV parsing ───────────────────────────────────────────────────────

    def test_tsv_parsing(self) -> None:
        content = b"name\tage\nAlice\t30\nBob\t25"
        result = self.adapter.extract(content, "test.tsv")
        assert len(result.text_blocks) == 3
        assert result.metadata["delimiter"] == "\t"

    # ── Fixture file ──────────────────────────────────────────────────────

    def test_fixture_file(self) -> None:
        import pathlib

        fixture = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "sample.csv"
        content = fixture.read_bytes()
        result = self.adapter.extract(content, "sample.csv")
        # Header + 3 data rows = 4 blocks
        assert len(result.text_blocks) == 4
        assert result.metadata["columns"] == ["name", "age", "city"]

    @pytest.mark.parametrize(
        ("ext", "mime"),
        [
            (".csv", "text/csv"),
            (".csv", "application/csv"),
            (".tsv", "text/tab-separated-values"),
        ],
    )
    def test_supported_formats(self, ext: str, mime: str) -> None:
        assert self.adapter.can_handle(f"file{ext}", mime)

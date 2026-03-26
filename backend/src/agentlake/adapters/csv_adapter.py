"""CSV / TSV file adapter."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from agentlake.adapters.base import ExtractedContent, TextBlock


class CsvAdapter:
    """Extracts text from CSV and TSV files.

    Each row is emitted as a :class:`TextBlock` with source locator
    ``row:{n}`` (1-indexed, header row included).
    """

    supported_extensions: list[str] = [".csv", ".tsv"]
    supported_mimetypes: list[str] = [
        "text/csv",
        "text/tab-separated-values",
        "application/csv",
    ]

    def can_handle(self, filename: str, content_type: str) -> bool:
        return (
            Path(filename).suffix.lower() in self.supported_extensions
            or content_type in self.supported_mimetypes
        )

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Parse CSV/TSV into row-level text blocks.

        Args:
            file_bytes: Raw CSV/TSV bytes (UTF-8).
            filename: Original filename.

        Returns:
            Extracted content with one block per non-empty row.
        """
        text = file_bytes.decode("utf-8", errors="replace")
        suffix = Path(filename).suffix.lower()
        delimiter = "\t" if suffix == ".tsv" else ","

        reader = csv.reader(io.StringIO(text), delimiter=delimiter)

        blocks: list[TextBlock] = []
        position = 0
        header: list[str] | None = None

        for row_idx, row in enumerate(reader, start=1):
            if not any(cell.strip() for cell in row):
                continue

            if header is None:
                header = row
                row_text = " | ".join(row)
            else:
                # Format as "header: value" pairs when header is available
                parts: list[str] = []
                for col_idx, cell in enumerate(row):
                    col_name = header[col_idx] if col_idx < len(header) else f"col{col_idx}"
                    parts.append(f"{col_name}: {cell}")
                row_text = " | ".join(parts)

            blocks.append(
                TextBlock(
                    content=row_text,
                    block_type="table",
                    position=position,
                    source_locator=f"row:{row_idx}",
                    metadata={"row": row_idx},
                )
            )
            position += 1

        metadata: dict = {
            "filename": filename,
            "delimiter": delimiter,
            "row_count": position,
        }
        if header:
            metadata["columns"] = header

        return ExtractedContent(text_blocks=blocks, metadata=metadata)

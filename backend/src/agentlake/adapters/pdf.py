"""PDF file adapter using PyMuPDF (fitz)."""

from __future__ import annotations

from pathlib import Path

from agentlake.adapters.base import ExtractedContent, StructureMarker, TextBlock


class PdfAdapter:
    """Extracts text from PDF files using PyMuPDF.

    Each page is emitted as one or more :class:`TextBlock` entries with
    ``source_locator`` set to ``page:{n}`` (1-indexed).
    """

    supported_extensions: list[str] = [".pdf"]
    supported_mimetypes: list[str] = ["application/pdf"]

    def can_handle(self, filename: str, content_type: str) -> bool:
        return (
            Path(filename).suffix.lower() in self.supported_extensions
            or content_type in self.supported_mimetypes
        )

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Extract text from each page of a PDF.

        Args:
            file_bytes: Raw PDF bytes.
            filename: Original filename.

        Returns:
            Extracted content with per-page text blocks and document metadata.
        """
        import fitz  # PyMuPDF

        doc = fitz.open(stream=file_bytes, filetype="pdf")

        metadata: dict = {"filename": filename, "page_count": len(doc)}
        pdf_meta = doc.metadata
        if pdf_meta:
            if pdf_meta.get("title"):
                metadata["title"] = pdf_meta["title"]
            if pdf_meta.get("author"):
                metadata["author"] = pdf_meta["author"]
            if pdf_meta.get("subject"):
                metadata["subject"] = pdf_meta["subject"]
            if pdf_meta.get("keywords"):
                metadata["keywords"] = pdf_meta["keywords"]
            if pdf_meta.get("creator"):
                metadata["creator"] = pdf_meta["creator"]

        blocks: list[TextBlock] = []
        structure: list[StructureMarker] = []
        position = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_number = page_num + 1  # 1-indexed

            if page_num > 0:
                structure.append(
                    StructureMarker(
                        marker_type="page_break",
                        position=position,
                        metadata={"page": page_number},
                    )
                )

            text = page.get_text("text").strip()
            if text:
                blocks.append(
                    TextBlock(
                        content=text,
                        block_type="paragraph",
                        position=position,
                        source_locator=f"page:{page_number}",
                        metadata={"page": page_number},
                    )
                )
                position += 1

        doc.close()

        return ExtractedContent(
            text_blocks=blocks,
            metadata=metadata,
            structure=structure,
        )

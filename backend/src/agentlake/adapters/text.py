"""Plain-text file adapter."""

from __future__ import annotations

from pathlib import Path

from agentlake.adapters.base import ExtractedContent, TextBlock


class TextAdapter:
    """Extracts content from plain ``.txt`` files.

    Splits text on double newlines into paragraph blocks, tracking the
    starting line number for each paragraph as the source locator.
    """

    supported_extensions: list[str] = [".txt"]
    supported_mimetypes: list[str] = ["text/plain"]

    def can_handle(self, filename: str, content_type: str) -> bool:
        """Return ``True`` for ``.txt`` files or ``text/plain`` MIME type."""
        return (
            Path(filename).suffix.lower() in self.supported_extensions
            or content_type in self.supported_mimetypes
        )

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Split plain text into paragraph blocks.

        Args:
            file_bytes: Raw UTF-8 encoded text.
            filename: Original filename.

        Returns:
            Extracted paragraphs with line-based source locators.
        """
        text = file_bytes.decode("utf-8", errors="replace")
        lines = text.split("\n")

        blocks: list[TextBlock] = []
        current_lines: list[str] = []
        block_start_line = 1
        position = 0

        for i, line in enumerate(lines, start=1):
            if line.strip() == "" and current_lines:
                # Check if the accumulated block is just whitespace
                content = "\n".join(current_lines).strip()
                if content:
                    blocks.append(
                        TextBlock(
                            content=content,
                            block_type="paragraph",
                            position=position,
                            source_locator=f"line:{block_start_line}",
                        )
                    )
                    position += 1
                current_lines = []
                block_start_line = i + 1
            elif line.strip() == "":
                block_start_line = i + 1
            else:
                if not current_lines:
                    block_start_line = i
                current_lines.append(line)

        # Flush remaining content
        if current_lines:
            content = "\n".join(current_lines).strip()
            if content:
                blocks.append(
                    TextBlock(
                        content=content,
                        block_type="paragraph",
                        position=position,
                        source_locator=f"line:{block_start_line}",
                    )
                )

        return ExtractedContent(
            text_blocks=blocks,
            metadata={"filename": filename, "encoding": "utf-8"},
        )

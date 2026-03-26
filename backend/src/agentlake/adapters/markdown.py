"""Markdown file adapter with frontmatter and structure parsing."""

from __future__ import annotations

import re
from pathlib import Path

from agentlake.adapters.base import ExtractedContent, StructureMarker, TextBlock


class MarkdownAdapter:
    """Extracts structured content from Markdown files.

    Handles YAML frontmatter (stripped from content, stored in metadata),
    headings, fenced code blocks, and paragraphs.
    """

    supported_extensions: list[str] = [".md", ".markdown", ".mkd"]
    supported_mimetypes: list[str] = ["text/markdown", "text/x-markdown"]

    _FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
    _FENCE_RE = re.compile(r"^```(\w*)")

    def can_handle(self, filename: str, content_type: str) -> bool:
        return (
            Path(filename).suffix.lower() in self.supported_extensions
            or content_type in self.supported_mimetypes
        )

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Parse markdown into structured text blocks.

        Args:
            file_bytes: Raw UTF-8 markdown content.
            filename: Original filename.

        Returns:
            Extracted content with headings, paragraphs, and code blocks.
        """
        text = file_bytes.decode("utf-8", errors="replace")
        metadata: dict = {"filename": filename}

        # Extract YAML frontmatter
        fm_match = self._FRONTMATTER_RE.match(text)
        if fm_match:
            metadata["frontmatter_raw"] = fm_match.group(1)
            try:
                import yaml

                metadata["frontmatter"] = yaml.safe_load(fm_match.group(1)) or {}
            except Exception:
                metadata["frontmatter"] = {}
            text = text[fm_match.end() :]

        blocks: list[TextBlock] = []
        structure: list[StructureMarker] = []
        lines = text.split("\n")
        position = 0
        in_code_block = False
        code_lang = ""
        code_lines: list[str] = []
        code_start_line = 0
        paragraph_lines: list[str] = []
        para_start_line = 0

        def _flush_paragraph() -> None:
            nonlocal paragraph_lines, position, para_start_line
            if paragraph_lines:
                content = "\n".join(paragraph_lines).strip()
                if content:
                    blocks.append(
                        TextBlock(
                            content=content,
                            block_type="paragraph",
                            position=position,
                            source_locator=f"line:{para_start_line}",
                        )
                    )
                    position += 1
                paragraph_lines = []

        for i, line in enumerate(lines, start=1):
            # Code fence toggle
            fence_match = self._FENCE_RE.match(line)
            if fence_match and not in_code_block:
                _flush_paragraph()
                in_code_block = True
                code_lang = fence_match.group(1) or "text"
                code_lines = []
                code_start_line = i
                structure.append(
                    StructureMarker(
                        marker_type="code_start",
                        position=position,
                        metadata={"language": code_lang},
                    )
                )
                continue
            if line.strip().startswith("```") and in_code_block:
                blocks.append(
                    TextBlock(
                        content="\n".join(code_lines),
                        block_type="code",
                        position=position,
                        source_locator=f"line:{code_start_line}",
                        metadata={"language": code_lang},
                    )
                )
                structure.append(
                    StructureMarker(marker_type="code_end", position=position)
                )
                position += 1
                in_code_block = False
                code_lines = []
                continue
            if in_code_block:
                code_lines.append(line)
                continue

            # Heading
            heading_match = self._HEADING_RE.match(line)
            if heading_match:
                _flush_paragraph()
                level = len(heading_match.group(1))
                blocks.append(
                    TextBlock(
                        content=heading_match.group(2).strip(),
                        block_type="heading",
                        position=position,
                        source_locator=f"line:{i}",
                        metadata={"level": level},
                    )
                )
                structure.append(
                    StructureMarker(
                        marker_type="section_start",
                        position=position,
                        metadata={"level": level, "title": heading_match.group(2).strip()},
                    )
                )
                position += 1
                continue

            # Blank line — flush paragraph
            if line.strip() == "":
                _flush_paragraph()
                continue

            # Accumulate paragraph
            if not paragraph_lines:
                para_start_line = i
            paragraph_lines.append(line)

        # Flush remaining
        if in_code_block and code_lines:
            blocks.append(
                TextBlock(
                    content="\n".join(code_lines),
                    block_type="code",
                    position=position,
                    source_locator=f"line:{code_start_line}",
                    metadata={"language": code_lang},
                )
            )
            position += 1
        _flush_paragraph()

        return ExtractedContent(
            text_blocks=blocks,
            metadata=metadata,
            structure=structure,
        )

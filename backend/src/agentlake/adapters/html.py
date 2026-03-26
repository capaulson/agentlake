"""HTML file adapter — extracts text by stripping tags."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from agentlake.adapters.base import ExtractedContent, TextBlock


class _HTMLTextExtractor(HTMLParser):
    """Simple HTML parser that extracts visible text content."""

    # Tags whose content should be skipped entirely
    _SKIP_TAGS = {"script", "style", "noscript", "template"}
    # Tags that represent block-level breaks
    _BLOCK_TAGS = {
        "p", "div", "section", "article", "aside", "header", "footer",
        "nav", "main", "blockquote", "pre", "ol", "ul", "li", "dl",
        "dt", "dd", "table", "tr", "th", "td", "caption", "figcaption",
        "figure", "hr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
    }

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[dict] = []
        self._current: list[str] = []
        self._skip_depth = 0
        self._element_count = 0
        self._current_tag = "body"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in self._BLOCK_TAGS:
            self._flush()
            self._current_tag = tag
            self._element_count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in self._BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            self._current.append(text)

    def _flush(self) -> None:
        if self._current:
            content = " ".join(self._current).strip()
            if content:
                self.blocks.append({
                    "content": content,
                    "tag": self._current_tag,
                    "element": self._element_count,
                })
            self._current = []


class HtmlAdapter:
    """Extracts visible text from HTML files by stripping tags.

    Source locators follow the pattern ``element:{n}`` (sequential count
    of block-level elements encountered).
    """

    supported_extensions: list[str] = [".html", ".htm"]
    supported_mimetypes: list[str] = ["text/html", "application/xhtml+xml"]

    def can_handle(self, filename: str, content_type: str) -> bool:
        return (
            Path(filename).suffix.lower() in self.supported_extensions
            or content_type in self.supported_mimetypes
        )

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Strip HTML tags and extract visible text.

        Args:
            file_bytes: Raw HTML bytes.
            filename: Original filename.

        Returns:
            Extracted content with element-based text blocks.
        """
        text = file_bytes.decode("utf-8", errors="replace")

        # Extract <title> for metadata
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        metadata: dict = {"filename": filename}
        if title_match:
            metadata["title"] = title_match.group(1).strip()

        extractor = _HTMLTextExtractor()
        extractor.feed(text)
        extractor._flush()  # Flush any remaining content

        blocks: list[TextBlock] = []
        heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}

        for position, block_info in enumerate(extractor.blocks):
            tag = block_info["tag"]
            block_type = "heading" if tag in heading_tags else "paragraph"
            block_metadata: dict = {"html_tag": tag}

            if tag in heading_tags:
                level = int(tag[1])
                block_metadata["level"] = level

            blocks.append(
                TextBlock(
                    content=block_info["content"],
                    block_type=block_type,
                    position=position,
                    source_locator=f"element:{block_info['element']}",
                    metadata=block_metadata,
                )
            )

        return ExtractedContent(text_blocks=blocks, metadata=metadata)

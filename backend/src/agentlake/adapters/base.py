"""Base types and protocol for file content extraction adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class TextBlock:
    """A single extracted block of text from a document.

    Attributes:
        content: The text content of the block.
        block_type: Semantic type — one of ``paragraph``, ``heading``,
            ``code``, ``table``, ``list``, ``image_description``.
        position: Sequential position of this block within the document.
        source_locator: Human-readable locator back to the original source,
            e.g. ``page:3``, ``slide:5``, ``sheet:Revenue``, ``line:42``.
        metadata: Arbitrary extra metadata for this block.
    """

    content: str
    block_type: str
    position: int
    source_locator: str
    metadata: dict = field(default_factory=dict)


@dataclass
class StructureMarker:
    """Marks a structural boundary in the extracted content.

    Attributes:
        marker_type: One of ``page_break``, ``section_start``,
            ``table_start``, ``table_end``, ``code_start``, ``code_end``.
        position: Sequential position aligned with :class:`TextBlock` positions.
        metadata: Extra info (e.g. section title, table caption).
    """

    marker_type: str
    position: int
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractedContent:
    """Result of extracting content from a file.

    Attributes:
        text_blocks: Ordered list of text blocks.
        metadata: Document-level metadata (title, author, page count, etc.).
        structure: Structural markers interleaved with text blocks.
    """

    text_blocks: list[TextBlock]
    metadata: dict = field(default_factory=dict)
    structure: list[StructureMarker] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Concatenate all text blocks into a single string."""
        return "\n\n".join(block.content for block in self.text_blocks)


class FileAdapter(Protocol):
    """Protocol that all file-type adapters must satisfy.

    Implementations are discovered automatically by :class:`AdapterRegistry`.
    """

    supported_extensions: list[str]
    supported_mimetypes: list[str]

    def can_handle(self, filename: str, content_type: str) -> bool:
        """Return ``True`` if this adapter can process the given file."""
        ...

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Extract structured text content from raw file bytes."""
        ...

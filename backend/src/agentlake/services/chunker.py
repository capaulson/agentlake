"""Semantic chunker for splitting extracted content into searchable chunks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import structlog
import tiktoken

from agentlake.adapters.base import ExtractedContent, TextBlock

logger = structlog.get_logger(__name__)

# Module-level tokenizer (thread-safe, reusable)
_ENCODING: tiktoken.Encoding | None = None


def _get_encoding() -> tiktoken.Encoding:
    """Return cached tiktoken cl100k_base encoding."""
    global _ENCODING  # noqa: PLW0603
    if _ENCODING is None:
        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return _ENCODING


def count_tokens(text: str) -> int:
    """Count tokens using cl100k_base encoding.

    Args:
        text: Input text to tokenize.

    Returns:
        Number of tokens.
    """
    return len(_get_encoding().encode(text))


def _content_hash(text: str) -> str:
    """Compute SHA-256 hex digest for chunk content.

    Args:
        text: Chunk text content.

    Returns:
        64-character hex digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Chunk:
    """A single content chunk produced by the semantic chunker.

    Attributes:
        content: The chunk text.
        chunk_index: Zero-based index within the document.
        source_locator: Human-readable locator from the first block.
        token_count: Number of tokens (cl100k_base).
        content_hash: SHA-256 hex digest of content.
        text_blocks: Original text blocks that contributed to this chunk.
    """

    content: str
    chunk_index: int
    source_locator: str
    token_count: int
    content_hash: str
    text_blocks: list[TextBlock] = field(default_factory=list)


# Block types that should not be split across chunks
_ATOMIC_BLOCK_TYPES = frozenset({"table", "code", "image_description"})

# Sentence boundary pattern
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\'\(])")


class SemanticChunker:
    """Splits extracted content into semantically meaningful chunks.

    Respects structural boundaries (tables, code blocks stay together),
    splits at paragraph boundaries first, falls back to sentence splitting
    for oversized paragraphs, and applies token-based overlap.

    Args:
        max_tokens: Maximum tokens per chunk.
        overlap_tokens: Number of overlap tokens between consecutive chunks.
    """

    def __init__(self, max_tokens: int = 1024, overlap_tokens: int = 64) -> None:
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, extracted: ExtractedContent) -> list[Chunk]:
        """Chunk extracted content respecting structural boundaries.

        Args:
            extracted: Content extracted by a file adapter.

        Returns:
            Ordered list of chunks with hashes and source locators.
        """
        if not extracted.text_blocks:
            logger.warning("chunker_empty_content", blocks=0)
            return []

        # Step 1: Group blocks into segments that should stay together
        segments = self._group_segments(extracted.text_blocks)

        # Step 2: Split segments into chunks respecting max_tokens
        raw_chunks = self._split_segments(segments)

        # Step 3: Apply overlap between consecutive chunks
        chunks = self._apply_overlap(raw_chunks)

        logger.info(
            "chunking_complete",
            input_blocks=len(extracted.text_blocks),
            output_chunks=len(chunks),
            total_tokens=sum(c.token_count for c in chunks),
        )

        return chunks

    def _group_segments(
        self, blocks: list[TextBlock]
    ) -> list[list[TextBlock]]:
        """Group text blocks into segments.

        Atomic block types (tables, code) form their own segment.
        Consecutive paragraph/heading/list blocks are grouped together.

        Args:
            blocks: Ordered text blocks.

        Returns:
            List of block groups (segments).
        """
        segments: list[list[TextBlock]] = []
        current_segment: list[TextBlock] = []

        for block in blocks:
            if block.block_type in _ATOMIC_BLOCK_TYPES:
                # Flush any accumulated regular blocks
                if current_segment:
                    segments.append(current_segment)
                    current_segment = []
                # Atomic block is its own segment
                segments.append([block])
            else:
                current_segment.append(block)

        if current_segment:
            segments.append(current_segment)

        return segments

    def _split_segments(
        self, segments: list[list[TextBlock]]
    ) -> list[_RawChunk]:
        """Split segments into raw chunks respecting token limits.

        Args:
            segments: Grouped text block segments.

        Returns:
            List of raw chunks (before overlap).
        """
        raw_chunks: list[_RawChunk] = []
        current_blocks: list[TextBlock] = []
        current_text_parts: list[str] = []
        current_tokens = 0

        for segment in segments:
            segment_text = "\n\n".join(b.content for b in segment)
            segment_tokens = count_tokens(segment_text)

            # If a single segment exceeds max_tokens, split it further
            if segment_tokens > self.max_tokens:
                # Flush current accumulator
                if current_text_parts:
                    raw_chunks.append(
                        _RawChunk(
                            text_parts=current_text_parts,
                            blocks=current_blocks,
                            tokens=current_tokens,
                        )
                    )
                    current_blocks = []
                    current_text_parts = []
                    current_tokens = 0

                # Split the oversized segment
                sub_chunks = self._split_oversized_segment(segment)
                raw_chunks.extend(sub_chunks)
                continue

            # Check if adding this segment would exceed the limit
            combined_tokens = current_tokens + segment_tokens
            if current_text_parts:
                # Account for the join separator
                combined_tokens += count_tokens("\n\n")

            if combined_tokens > self.max_tokens and current_text_parts:
                # Flush current chunk
                raw_chunks.append(
                    _RawChunk(
                        text_parts=current_text_parts,
                        blocks=current_blocks,
                        tokens=current_tokens,
                    )
                )
                current_blocks = []
                current_text_parts = []
                current_tokens = 0

            current_text_parts.append(segment_text)
            current_blocks.extend(segment)
            current_tokens = count_tokens("\n\n".join(current_text_parts))

        # Flush remaining
        if current_text_parts:
            raw_chunks.append(
                _RawChunk(
                    text_parts=current_text_parts,
                    blocks=current_blocks,
                    tokens=current_tokens,
                )
            )

        return raw_chunks

    def _split_oversized_segment(
        self, segment: list[TextBlock]
    ) -> list[_RawChunk]:
        """Split an oversized segment by paragraph, then sentence boundaries.

        Args:
            segment: A group of text blocks that exceeds max_tokens.

        Returns:
            List of raw chunks.
        """
        raw_chunks: list[_RawChunk] = []

        for block in segment:
            block_tokens = count_tokens(block.content)

            if block_tokens <= self.max_tokens:
                # Block fits in a single chunk
                raw_chunks.append(
                    _RawChunk(
                        text_parts=[block.content],
                        blocks=[block],
                        tokens=block_tokens,
                    )
                )
                continue

            # Split by sentences
            sentences = self._split_sentences(block.content)
            current_parts: list[str] = []
            current_tokens = 0

            for sentence in sentences:
                sentence_tokens = count_tokens(sentence)

                # If a single sentence exceeds max, hard-split it
                if sentence_tokens > self.max_tokens:
                    if current_parts:
                        text = " ".join(current_parts)
                        raw_chunks.append(
                            _RawChunk(
                                text_parts=[text],
                                blocks=[block],
                                tokens=count_tokens(text),
                            )
                        )
                        current_parts = []
                        current_tokens = 0

                    # Hard split by token count
                    hard_splits = self._hard_split(sentence)
                    for split_text in hard_splits:
                        raw_chunks.append(
                            _RawChunk(
                                text_parts=[split_text],
                                blocks=[block],
                                tokens=count_tokens(split_text),
                            )
                        )
                    continue

                test_tokens = current_tokens + sentence_tokens
                if current_parts:
                    test_tokens += 1  # space separator

                if test_tokens > self.max_tokens and current_parts:
                    text = " ".join(current_parts)
                    raw_chunks.append(
                        _RawChunk(
                            text_parts=[text],
                            blocks=[block],
                            tokens=count_tokens(text),
                        )
                    )
                    current_parts = []
                    current_tokens = 0

                current_parts.append(sentence)
                current_tokens = count_tokens(" ".join(current_parts))

            if current_parts:
                text = " ".join(current_parts)
                raw_chunks.append(
                    _RawChunk(
                        text_parts=[text],
                        blocks=[block],
                        tokens=count_tokens(text),
                    )
                )

        return raw_chunks

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences.

        Args:
            text: Text to split.

        Returns:
            List of sentence strings.
        """
        sentences = _SENTENCE_RE.split(text)
        return [s.strip() for s in sentences if s.strip()]

    def _hard_split(self, text: str) -> list[str]:
        """Hard-split text by token count when no sentence boundary works.

        Args:
            text: Oversized text to split.

        Returns:
            List of text segments each within max_tokens.
        """
        enc = _get_encoding()
        tokens = enc.encode(text)
        parts: list[str] = []

        for i in range(0, len(tokens), self.max_tokens):
            segment_tokens = tokens[i : i + self.max_tokens]
            parts.append(enc.decode(segment_tokens))

        return parts

    def _apply_overlap(self, raw_chunks: list[_RawChunk]) -> list[Chunk]:
        """Apply overlap between consecutive chunks.

        Prepends the last ``overlap_tokens`` tokens from the previous
        chunk to the current one.

        Args:
            raw_chunks: Raw chunks before overlap.

        Returns:
            Final list of Chunk objects.
        """
        if not raw_chunks:
            return []

        enc = _get_encoding()
        chunks: list[Chunk] = []

        for idx, raw in enumerate(raw_chunks):
            content = "\n\n".join(raw.text_parts)

            # Apply overlap from previous chunk
            if idx > 0 and self.overlap_tokens > 0:
                prev_content = "\n\n".join(raw_chunks[idx - 1].text_parts)
                prev_tokens = enc.encode(prev_content)
                if len(prev_tokens) > self.overlap_tokens:
                    overlap_text = enc.decode(
                        prev_tokens[-self.overlap_tokens :]
                    )
                    content = overlap_text + "\n\n" + content

            token_count = count_tokens(content)
            source_locator = (
                raw.blocks[0].source_locator if raw.blocks else "unknown"
            )

            chunks.append(
                Chunk(
                    content=content,
                    chunk_index=idx,
                    source_locator=source_locator,
                    token_count=token_count,
                    content_hash=_content_hash(content),
                    text_blocks=list(raw.blocks),
                )
            )

        return chunks


@dataclass
class _RawChunk:
    """Internal intermediate chunk before overlap is applied."""

    text_parts: list[str]
    blocks: list[TextBlock]
    tokens: int

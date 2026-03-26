"""Source code file adapter."""

from __future__ import annotations

from pathlib import Path

from agentlake.adapters.base import ExtractedContent, TextBlock

# Map file extensions to language identifiers for metadata.
_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".java": "java",
    ".rb": "ruby",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".r": "r",
    ".R": "r",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".php": "php",
    ".pl": "perl",
    ".lua": "lua",
    ".zig": "zig",
    ".nim": "nim",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".clj": "clojure",
}


class CodeAdapter:
    """Extracts content from source code files.

    The entire file is treated as a single code block, with the
    programming language inferred from the file extension.  Source
    locators use ``line:{start}-{end}`` ranges.
    """

    supported_extensions: list[str] = list(_EXTENSION_LANGUAGE_MAP.keys())
    supported_mimetypes: list[str] = [
        "text/x-python",
        "text/javascript",
        "text/typescript",
        "text/x-go",
        "text/x-rust",
        "text/x-c",
        "text/x-c++",
        "text/x-java",
        "text/x-ruby",
        "text/x-shellscript",
        "application/javascript",
        "application/typescript",
    ]

    # Maximum lines per block before splitting.
    _MAX_LINES_PER_BLOCK: int = 200

    def can_handle(self, filename: str, content_type: str) -> bool:
        return (
            Path(filename).suffix.lower() in self.supported_extensions
            or content_type in self.supported_mimetypes
        )

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Extract source code as code blocks.

        For large files the code is split into chunks of up to
        ``_MAX_LINES_PER_BLOCK`` lines to keep block sizes manageable.

        Args:
            file_bytes: Raw source code bytes.
            filename: Original filename.

        Returns:
            Extracted content with code-typed text blocks.
        """
        text = file_bytes.decode("utf-8", errors="replace")
        lines = text.split("\n")
        suffix = Path(filename).suffix.lower()
        language = _EXTENSION_LANGUAGE_MAP.get(suffix, "text")

        metadata: dict = {
            "filename": filename,
            "language": language,
            "line_count": len(lines),
        }

        blocks: list[TextBlock] = []
        position = 0
        max_lines = self._MAX_LINES_PER_BLOCK

        for chunk_start in range(0, len(lines), max_lines):
            chunk_end = min(chunk_start + max_lines, len(lines))
            chunk_lines = lines[chunk_start:chunk_end]
            content = "\n".join(chunk_lines)

            if not content.strip():
                continue

            start_line = chunk_start + 1  # 1-indexed
            end_line = chunk_end

            blocks.append(
                TextBlock(
                    content=content,
                    block_type="code",
                    position=position,
                    source_locator=f"line:{start_line}-{end_line}",
                    metadata={"language": language, "start_line": start_line, "end_line": end_line},
                )
            )
            position += 1

        return ExtractedContent(text_blocks=blocks, metadata=metadata)

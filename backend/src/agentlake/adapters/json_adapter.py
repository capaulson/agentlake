"""JSON, YAML, and XML file adapter."""

from __future__ import annotations

import json
from pathlib import Path

from agentlake.adapters.base import ExtractedContent, TextBlock


class JsonYamlAdapter:
    """Extracts text from JSON, YAML, and XML files.

    Structured data is flattened to key-path text blocks.  XML is
    converted to a simplified text representation.
    """

    supported_extensions: list[str] = [".json", ".yaml", ".yml", ".xml"]
    supported_mimetypes: list[str] = [
        "application/json",
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/xml",
        "application/xml",
    ]

    def can_handle(self, filename: str, content_type: str) -> bool:
        return (
            Path(filename).suffix.lower() in self.supported_extensions
            or content_type in self.supported_mimetypes
        )

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Parse and convert structured data to text blocks.

        Args:
            file_bytes: Raw file bytes.
            filename: Original filename.

        Returns:
            Extracted content with key-path based text blocks.
        """
        text = file_bytes.decode("utf-8", errors="replace")
        suffix = Path(filename).suffix.lower()

        if suffix == ".xml":
            return self._extract_xml(text, filename)
        elif suffix in (".yaml", ".yml"):
            return self._extract_yaml(text, filename)
        else:
            return self._extract_json(text, filename)

    def _extract_json(self, text: str, filename: str) -> ExtractedContent:
        """Extract from JSON."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return ExtractedContent(
                text_blocks=[
                    TextBlock(
                        content=text,
                        block_type="paragraph",
                        position=0,
                        source_locator="key:$",
                        metadata={"parse_error": True},
                    )
                ],
                metadata={"filename": filename, "format": "json", "parse_error": True},
            )

        blocks = self._flatten_to_blocks(data, "$")
        return ExtractedContent(
            text_blocks=blocks,
            metadata={"filename": filename, "format": "json"},
        )

    def _extract_yaml(self, text: str, filename: str) -> ExtractedContent:
        """Extract from YAML."""
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception:
            return ExtractedContent(
                text_blocks=[
                    TextBlock(
                        content=text,
                        block_type="paragraph",
                        position=0,
                        source_locator="key:$",
                        metadata={"parse_error": True},
                    )
                ],
                metadata={"filename": filename, "format": "yaml", "parse_error": True},
            )

        if data is None:
            data = {}

        blocks = self._flatten_to_blocks(data, "$")
        return ExtractedContent(
            text_blocks=blocks,
            metadata={"filename": filename, "format": "yaml"},
        )

    def _extract_xml(self, text: str, filename: str) -> ExtractedContent:
        """Extract from XML using ElementTree."""
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(text)  # noqa: S314
        except ET.ParseError:
            return ExtractedContent(
                text_blocks=[
                    TextBlock(
                        content=text,
                        block_type="paragraph",
                        position=0,
                        source_locator="key:$",
                        metadata={"parse_error": True},
                    )
                ],
                metadata={"filename": filename, "format": "xml", "parse_error": True},
            )

        blocks: list[TextBlock] = []
        position = 0

        def _walk(element: ET.Element, path: str) -> None:
            nonlocal position
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
            current_path = f"{path}/{tag}"

            text_content = (element.text or "").strip()
            if text_content:
                blocks.append(
                    TextBlock(
                        content=text_content,
                        block_type="paragraph",
                        position=position,
                        source_locator=f"key:{current_path}",
                        metadata={"tag": tag, "attributes": dict(element.attrib)},
                    )
                )
                position += 1

            for child in element:
                _walk(child, current_path)

        _walk(root, "$")

        return ExtractedContent(
            text_blocks=blocks,
            metadata={"filename": filename, "format": "xml", "root_tag": root.tag},
        )

    def _flatten_to_blocks(
        self, data: object, prefix: str, _position: int = 0
    ) -> list[TextBlock]:
        """Recursively flatten a dict/list into text blocks with key paths."""
        blocks: list[TextBlock] = []
        position = _position

        if isinstance(data, dict):
            for key, value in data.items():
                path = f"{prefix}.{key}"
                if isinstance(value, (dict, list)):
                    sub_blocks = self._flatten_to_blocks(value, path, position)
                    blocks.extend(sub_blocks)
                    position += len(sub_blocks)
                else:
                    blocks.append(
                        TextBlock(
                            content=f"{key}: {value}",
                            block_type="paragraph",
                            position=position,
                            source_locator=f"key:{path}",
                        )
                    )
                    position += 1
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                path = f"{prefix}[{idx}]"
                if isinstance(item, (dict, list)):
                    sub_blocks = self._flatten_to_blocks(item, path, position)
                    blocks.extend(sub_blocks)
                    position += len(sub_blocks)
                else:
                    blocks.append(
                        TextBlock(
                            content=str(item),
                            block_type="paragraph",
                            position=position,
                            source_locator=f"key:{path}",
                        )
                    )
                    position += 1
        else:
            blocks.append(
                TextBlock(
                    content=str(data),
                    block_type="paragraph",
                    position=position,
                    source_locator=f"key:{prefix}",
                )
            )

        return blocks

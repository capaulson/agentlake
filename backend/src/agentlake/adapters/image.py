"""Image file adapter — extracts metadata and dimensions."""

from __future__ import annotations

import io
import struct
from pathlib import Path

from agentlake.adapters.base import ExtractedContent, TextBlock


class ImageAdapter:
    """Extracts metadata from image files.

    Since images cannot be directly converted to searchable text,
    this adapter produces a single :class:`TextBlock` describing the
    image's metadata (dimensions, format, EXIF data when available).
    """

    supported_extensions: list[str] = [
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ]
    supported_mimetypes: list[str] = [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/bmp",
        "image/webp",
        "image/tiff",
    ]

    def can_handle(self, filename: str, content_type: str) -> bool:
        return (
            Path(filename).suffix.lower() in self.supported_extensions
            or content_type in self.supported_mimetypes
        )

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        """Extract image metadata.

        Attempts to use Pillow for full EXIF extraction.  Falls back to
        basic header parsing if Pillow is not available.

        Args:
            file_bytes: Raw image bytes.
            filename: Original filename.

        Returns:
            A single text block describing the image metadata.
        """
        metadata: dict = {
            "filename": filename,
            "file_size": len(file_bytes),
            "format": Path(filename).suffix.lower().lstrip("."),
        }

        try:
            metadata.update(self._extract_with_pillow(file_bytes))
        except ImportError:
            metadata.update(self._extract_basic(file_bytes, filename))

        # Build a descriptive text block
        description_parts: list[str] = [f"Image file: {filename}"]
        if "width" in metadata and "height" in metadata:
            description_parts.append(f"Dimensions: {metadata['width']}x{metadata['height']}")
        if "format_name" in metadata:
            description_parts.append(f"Format: {metadata['format_name']}")
        if "mode" in metadata:
            description_parts.append(f"Color mode: {metadata['mode']}")
        if "exif" in metadata and metadata["exif"]:
            exif = metadata["exif"]
            if "Make" in exif:
                description_parts.append(f"Camera: {exif.get('Make', '')} {exif.get('Model', '')}")
            if "DateTime" in exif:
                description_parts.append(f"Taken: {exif['DateTime']}")
            if "GPSInfo" in exif:
                description_parts.append("GPS data present")

        description = "\n".join(description_parts)

        return ExtractedContent(
            text_blocks=[
                TextBlock(
                    content=description,
                    block_type="image_description",
                    position=0,
                    source_locator="image:1",
                    metadata=metadata,
                )
            ],
            metadata=metadata,
        )

    def _extract_with_pillow(self, file_bytes: bytes) -> dict:
        """Extract metadata using Pillow (PIL)."""
        from PIL import Image
        from PIL.ExifTags import TAGS

        img = Image.open(io.BytesIO(file_bytes))

        info: dict = {
            "width": img.width,
            "height": img.height,
            "format_name": img.format or "unknown",
            "mode": img.mode,
        }

        # EXIF data
        exif_data = {}
        try:
            raw_exif = img.getexif()
            if raw_exif:
                for tag_id, value in raw_exif.items():
                    tag_name = TAGS.get(tag_id, str(tag_id))
                    # Only include string-serialisable values
                    if isinstance(value, (str, int, float)):
                        exif_data[tag_name] = value
                    elif isinstance(value, bytes):
                        exif_data[tag_name] = value.hex()[:64]
        except Exception:
            pass

        if exif_data:
            info["exif"] = exif_data

        img.close()
        return info

    def _extract_basic(self, file_bytes: bytes, filename: str) -> dict:
        """Fallback: extract dimensions from raw image header bytes."""
        info: dict = {}
        suffix = Path(filename).suffix.lower()

        try:
            if suffix == ".png" and file_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                width = struct.unpack(">I", file_bytes[16:20])[0]
                height = struct.unpack(">I", file_bytes[20:24])[0]
                info["width"] = width
                info["height"] = height
                info["format_name"] = "PNG"

            elif suffix in (".jpg", ".jpeg") and file_bytes[:2] == b"\xff\xd8":
                info["format_name"] = "JPEG"
                # JPEG dimension parsing requires scanning markers
                # Keep it simple for the fallback
        except Exception:
            pass

        return info

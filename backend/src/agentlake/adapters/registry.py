"""Adapter registry — discovers and routes files to the correct adapter."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import structlog

from agentlake.adapters.base import ExtractedContent, FileAdapter

logger = structlog.get_logger(__name__)


class AdapterRegistry:
    """Central registry that maps file types to extraction adapters.

    Call :meth:`auto_discover` at application startup to populate the
    registry from all modules in the ``agentlake.adapters`` package.
    """

    def __init__(self) -> None:
        self._adapters: list[FileAdapter] = []

    def register(self, adapter: FileAdapter) -> None:
        """Register a single adapter instance.

        Args:
            adapter: An object satisfying the :class:`FileAdapter` protocol.
        """
        self._adapters.append(adapter)
        logger.debug(
            "adapter_registered",
            adapter=type(adapter).__name__,
            extensions=adapter.supported_extensions,
        )

    def get_adapter(self, filename: str, content_type: str) -> FileAdapter | None:
        """Return the first adapter that can handle the given file.

        Args:
            filename: Original filename (used for extension matching).
            content_type: MIME content type.

        Returns:
            A matching :class:`FileAdapter` instance, or ``None``.
        """
        for adapter in self._adapters:
            if adapter.can_handle(filename, content_type):
                return adapter
        return None

    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedContent:
        """Convenience: find the right adapter and extract content.

        Args:
            file_bytes: Raw file data.
            filename: Original filename.
            content_type: MIME content type.

        Returns:
            Extracted content from the matching adapter.

        Raises:
            ValueError: If no adapter can handle the file type.
        """
        adapter = self.get_adapter(filename, content_type)
        if adapter is None:
            raise ValueError(
                f"No adapter found for filename={filename!r} content_type={content_type!r}"
            )
        return adapter.extract(file_bytes, filename)

    def auto_discover(self) -> None:
        """Import all modules in the adapters package and register adapter instances.

        Any class that has ``supported_extensions`` and ``supported_mimetypes``
        attributes (and is not the Protocol itself) is instantiated and registered.
        """
        import agentlake.adapters as adapters_pkg

        package_path = Path(adapters_pkg.__file__).parent

        for module_info in pkgutil.iter_modules([str(package_path)]):
            if module_info.name in ("base", "registry"):
                continue
            module = importlib.import_module(f"agentlake.adapters.{module_info.name}")

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and hasattr(attr, "supported_extensions")
                    and hasattr(attr, "supported_mimetypes")
                    and hasattr(attr, "can_handle")
                    and hasattr(attr, "extract")
                    and attr.__module__ == module.__name__
                ):
                    try:
                        instance = attr()
                        self.register(instance)
                    except Exception:
                        logger.exception(
                            "adapter_instantiation_failed", adapter=attr_name
                        )

    @property
    def registered_adapters(self) -> list[FileAdapter]:
        """Return a copy of the registered adapter list."""
        return list(self._adapters)

    @property
    def supported_extensions(self) -> list[str]:
        """Return all file extensions supported by registered adapters."""
        extensions: list[str] = []
        for adapter in self._adapters:
            extensions.extend(adapter.supported_extensions)
        return sorted(set(extensions))

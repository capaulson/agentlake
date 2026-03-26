"""MCP resource definitions for AgentLake.

Exposes data lake content as MCP resources and resource templates:
  - agentlake://documents           -- paginated document list
  - agentlake://documents/{id}      -- single processed document
  - agentlake://vault/{file_id}     -- raw vault file metadata
  - agentlake://tags                -- tag listing
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import structlog
from mcp.server import Server
from mcp.types import Resource, ResourceTemplate

from agentlake.mcp.client import AgentLakeAPIError, AgentLakeClient

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# URI parsing helpers
# ---------------------------------------------------------------------------

# Pattern: agentlake://documents/<uuid>
_DOCUMENT_RE = re.compile(
    r"^agentlake://documents/([0-9a-fA-F\-]{36})$"
)
# Pattern: agentlake://vault/<uuid>
_VAULT_RE = re.compile(
    r"^agentlake://vault/([0-9a-fA-F\-]{36})$"
)


def _parse_uri(uri: str) -> tuple[str, str | None]:
    """Return (resource_type, id_or_none) from an agentlake:// URI.

    Examples:
        agentlake://documents          -> ("documents", None)
        agentlake://documents/<uuid>   -> ("document", "<uuid>")
        agentlake://vault/<uuid>       -> ("vault", "<uuid>")
        agentlake://tags               -> ("tags", None)
    """
    m = _DOCUMENT_RE.match(uri)
    if m:
        return ("document", m.group(1))

    m = _VAULT_RE.match(uri)
    if m:
        return ("vault", m.group(1))

    parsed = urlparse(uri)
    path = parsed.netloc + parsed.path  # urlparse puts host in netloc for custom schemes
    path = path.strip("/")

    if path == "documents":
        return ("documents", None)
    if path == "tags":
        return ("tags", None)

    return ("unknown", None)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_resources(server: Server, client: AgentLakeClient) -> None:
    """Register AgentLake resources and resource templates on the MCP server."""

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(
                uri="agentlake://documents",
                name="All Documents",
                description=(
                    "Paginated list of all processed documents in AgentLake "
                    "with their titles, categories, and metadata."
                ),
                mimeType="application/json",
            ),
            Resource(
                uri="agentlake://tags",
                name="All Tags",
                description="List of all tags in the data lake with file counts.",
                mimeType="application/json",
            ),
        ]

    @server.list_resource_templates()
    async def list_resource_templates() -> list[ResourceTemplate]:
        return [
            ResourceTemplate(
                uriTemplate="agentlake://documents/{document_id}",
                name="Document by ID",
                description=(
                    "Full processed document including markdown body, "
                    "YAML frontmatter metadata, entities, and citations."
                ),
                mimeType="text/markdown",
            ),
            ResourceTemplate(
                uriTemplate="agentlake://vault/{file_id}",
                name="Vault File",
                description=(
                    "Raw vault file metadata including filename, size, "
                    "MIME type, processing status, and download URI."
                ),
                mimeType="application/json",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        logger.info("mcp_read_resource", uri=uri)
        resource_type, resource_id = _parse_uri(uri)

        try:
            if resource_type == "documents":
                result = await client.list_documents(limit=20)
                return json.dumps(result, indent=2, default=str)

            elif resource_type == "document" and resource_id:
                result = await client.get_document(resource_id)
                # Return the markdown body directly when available for a
                # more natural reading experience; fall back to JSON.
                data = result.get("data", result)
                if isinstance(data, dict) and "body_markdown" in data:
                    return _format_document_markdown(data)
                return json.dumps(result, indent=2, default=str)

            elif resource_type == "vault" and resource_id:
                result = await client.get_file(resource_id)
                return json.dumps(result, indent=2, default=str)

            elif resource_type == "tags":
                result = await client.list_tags()
                return json.dumps(result, indent=2, default=str)

            else:
                return json.dumps(
                    {"error": f"Unknown resource URI: {uri}"}, indent=2
                )

        except AgentLakeAPIError as exc:
            logger.warning(
                "mcp_resource_api_error",
                uri=uri,
                status_code=exc.status_code,
                detail=exc.detail,
            )
            return json.dumps(
                {"error": f"API error {exc.status_code}: {exc.detail}"},
                indent=2,
            )
        except Exception as exc:
            logger.exception("mcp_resource_unexpected_error", uri=uri)
            return json.dumps({"error": str(exc)}, indent=2)


def _format_document_markdown(data: dict[str, Any]) -> str:
    """Format a document dict as readable markdown with frontmatter."""
    lines: list[str] = []

    # YAML-ish header
    lines.append("---")
    for key in ("id", "title", "category", "tags", "created_at", "updated_at"):
        if key in data:
            value = data[key]
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")

    # Body
    lines.append(data.get("body_markdown", ""))

    # Entities section
    entities = data.get("entities")
    if entities:
        lines.append("")
        lines.append("## Extracted Entities")
        lines.append("")
        for entity in entities:
            if isinstance(entity, dict):
                name = entity.get("name", "unknown")
                etype = entity.get("type", "")
                lines.append(f"- **{name}** ({etype})")
            else:
                lines.append(f"- {entity}")

    return "\n".join(lines)

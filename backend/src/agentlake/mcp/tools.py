"""MCP tool definitions for AgentLake.

Registers eight tools that wrap the AgentLake REST API:
  - agentlake_search
  - agentlake_get_document
  - agentlake_get_citations
  - agentlake_discover
  - agentlake_upload
  - agentlake_list_tags
  - agentlake_graph_explore
  - agentlake_edit_document
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from mcp.server import Server
from mcp.types import TextContent, Tool

from agentlake.mcp.client import AgentLakeAPIError, AgentLakeClient

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="agentlake_search",
        description=(
            "Search the AgentLake data lake for documents using hybrid "
            "(keyword + semantic), keyword-only, or semantic-only search. "
            "Supports filtering by category, tags, entities, and date range."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text",
                },
                "search_type": {
                    "type": "string",
                    "enum": ["hybrid", "keyword", "semantic"],
                    "default": "hybrid",
                    "description": "Search mode",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by document category",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by one or more tags",
                },
                "entities": {
                    "type": "string",
                    "description": "Filter by entity name",
                },
                "date_from": {
                    "type": "string",
                    "description": "ISO 8601 start date filter",
                },
                "date_to": {
                    "type": "string",
                    "description": "ISO 8601 end date filter",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of results (1-50)",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="agentlake_get_document",
        description=(
            "Retrieve a full processed document by ID, including its "
            "markdown body, YAML frontmatter metadata, extracted entities, "
            "and citation links back to source data."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "Document UUID",
                },
            },
            "required": ["document_id"],
        },
    ),
    Tool(
        name="agentlake_get_citations",
        description=(
            "Get all citations for a processed document. Each citation "
            "links a claim in the document back to a specific chunk in "
            "the original source file, providing full provenance."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "Document UUID",
                },
            },
            "required": ["document_id"],
        },
    ),
    Tool(
        name="agentlake_discover",
        description=(
            "Get an overview of the AgentLake data lake: total file and "
            "document counts, available categories, tags, entity types, "
            "and recent activity."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="agentlake_upload",
        description=(
            "Upload a local file to AgentLake for processing. The file is "
            "ingested into the vault, then asynchronously processed through "
            "the LLM pipeline into searchable markdown with citations. "
            "Supports PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, HTML, and more."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the local file to upload",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags to assign to the uploaded file",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="agentlake_list_tags",
        description=(
            "List all tags in the data lake with their associated file counts."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="agentlake_graph_explore",
        description=(
            "Explore the entity relationship graph. Either search for "
            "entities by name/type, or retrieve the neighbors of a known "
            "entity to understand its connections. Provide 'query' to "
            "search or 'entity_id' to get neighbors."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Entity name to search for",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Entity UUID to get neighbors for",
                },
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Filter by entity type (e.g. person, organization, "
                        "product, technology)"
                    ),
                },
                "depth": {
                    "type": "integer",
                    "default": 1,
                    "description": "Neighbor traversal depth (1-3)",
                },
            },
        },
    ),
    Tool(
        name="agentlake_edit_document",
        description=(
            "Edit a processed document's markdown content. Creates a new "
            "version with full diff tracking. A justification is required "
            "to explain why the edit was made."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "Document UUID to edit",
                },
                "body_markdown": {
                    "type": "string",
                    "description": "New markdown body content",
                },
                "justification": {
                    "type": "string",
                    "description": "Reason for the edit (recorded in diff log)",
                },
            },
            "required": ["document_id", "body_markdown", "justification"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_text(data: Any) -> list[TextContent]:
    """Wrap a Python object as a single JSON ``TextContent`` item."""
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _error_text(message: str) -> list[TextContent]:
    """Wrap an error message as a single ``TextContent`` item."""
    return [TextContent(type="text", text=f"Error: {message}")]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_tools(server: Server, client: AgentLakeClient) -> None:
    """Register all AgentLake tools on the MCP ``server``."""

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        logger.info("mcp_call_tool", tool=name, arguments=arguments)

        try:
            if name == "agentlake_search":
                result = await client.search(
                    query=arguments["query"],
                    search_type=arguments.get("search_type", "hybrid"),
                    limit=arguments.get("limit", 10),
                    category=arguments.get("category"),
                    tags=arguments.get("tags"),
                    entities=arguments.get("entities"),
                    date_from=arguments.get("date_from"),
                    date_to=arguments.get("date_to"),
                )
                return _json_text(result)

            elif name == "agentlake_get_document":
                result = await client.get_document(arguments["document_id"])
                return _json_text(result)

            elif name == "agentlake_get_citations":
                result = await client.get_citations(arguments["document_id"])
                return _json_text(result)

            elif name == "agentlake_discover":
                result = await client.discover()
                return _json_text(result)

            elif name == "agentlake_upload":
                result = await client.upload_file(
                    file_path=arguments["file_path"],
                    tags=arguments.get("tags"),
                )
                return _json_text(result)

            elif name == "agentlake_list_tags":
                result = await client.list_tags()
                return _json_text(result)

            elif name == "agentlake_graph_explore":
                query = arguments.get("query")
                entity_id = arguments.get("entity_id")

                if entity_id:
                    result = await client.get_entity_neighbors(
                        entity_id=entity_id,
                        depth=arguments.get("depth", 1),
                    )
                elif query:
                    result = await client.graph_search(
                        query=query,
                        entity_type=arguments.get("entity_type"),
                    )
                else:
                    return _error_text(
                        "Either 'query' or 'entity_id' must be provided."
                    )
                return _json_text(result)

            elif name == "agentlake_edit_document":
                result = await client.edit_document(
                    document_id=arguments["document_id"],
                    body_markdown=arguments["body_markdown"],
                    justification=arguments["justification"],
                )
                return _json_text(result)

            else:
                return _error_text(f"Unknown tool: {name}")

        except FileNotFoundError as exc:
            logger.warning("mcp_tool_file_not_found", tool=name, error=str(exc))
            return _error_text(str(exc))
        except AgentLakeAPIError as exc:
            logger.warning(
                "mcp_tool_api_error",
                tool=name,
                status_code=exc.status_code,
                detail=exc.detail,
            )
            return _error_text(f"API error {exc.status_code}: {exc.detail}")
        except Exception as exc:
            logger.exception("mcp_tool_unexpected_error", tool=name)
            return _error_text(f"Unexpected error: {exc}")

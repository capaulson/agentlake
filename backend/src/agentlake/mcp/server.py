"""AgentLake MCP Server.

Wraps the AgentLake REST API and exposes it via the Model Context Protocol
for use with Claude Desktop, Claude Code, and other MCP clients.

Usage:
    stdio:  python -m agentlake.mcp.server --transport stdio
    SSE:    python -m agentlake.mcp.server --transport sse --port 8002
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server

from agentlake.mcp.client import AgentLakeClient
from agentlake.mcp.prompts import register_prompts
from agentlake.mcp.resources import register_resources
from agentlake.mcp.tools import register_tools

logger = structlog.get_logger(__name__)


def create_server() -> tuple[Server, AgentLakeClient]:
    """Create and configure the MCP server with all handlers.

    Returns:
        A tuple of (server, client) so the caller can manage the client
        lifecycle (e.g. close it on shutdown).
    """
    api_url = os.environ.get("AGENTLAKE_API_URL", "http://localhost:8000")
    api_key = os.environ.get(
        "MCP_SERVER_API_KEY",
        os.environ.get("AGENTLAKE_API_KEY", ""),
    )

    logger.info(
        "mcp_server_create",
        api_url=api_url,
        api_key_set=bool(api_key),
    )

    client = AgentLakeClient(base_url=api_url, api_key=api_key)

    mcp_server = Server("agentlake")
    register_tools(mcp_server, client)
    register_resources(mcp_server, client)
    register_prompts(mcp_server, client)

    return mcp_server, client


# ---------------------------------------------------------------------------
# Transport: stdio
# ---------------------------------------------------------------------------


async def run_stdio() -> None:
    """Run the MCP server over stdio (for Claude Desktop / Claude Code)."""
    mcp_server, client = create_server()
    logger.info("mcp_server_start", transport="stdio")

    try:
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )
    finally:
        await client.close()
        logger.info("mcp_server_stop", transport="stdio")


# ---------------------------------------------------------------------------
# Transport: SSE
# ---------------------------------------------------------------------------


async def run_sse(host: str, port: int) -> None:
    """Run the MCP server over SSE (HTTP-based, for remote clients).

    Starts a Starlette/Uvicorn application with two routes:
        GET  /sse           -- SSE connection endpoint
        POST /messages/     -- message posting endpoint
    """
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.routing import Mount, Route

    import uvicorn

    mcp_server, client = create_server()
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0],
                streams[1],
                mcp_server.create_initialization_options(),
            )

    async def handle_health(request: Request):
        from starlette.responses import JSONResponse

        return JSONResponse({"status": "ok", "server": "agentlake-mcp"})

    starlette_app = Starlette(
        routes=[
            Route("/health", endpoint=handle_health, methods=["GET"]),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ],
    )

    logger.info("mcp_server_start", transport="sse", host=host, port=port)

    config = uvicorn.Config(
        starlette_app,
        host=host,
        port=port,
        log_level="info",
    )
    server_instance = uvicorn.Server(config)

    try:
        await server_instance.serve()
    finally:
        await client.close()
        logger.info("mcp_server_stop", transport="sse")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the AgentLake MCP server."""
    parser = argparse.ArgumentParser(
        description="AgentLake MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  AGENTLAKE_API_URL    Base URL of the AgentLake API "
            "(default: http://localhost:8000)\n"
            "  MCP_SERVER_API_KEY   API key for authenticating with AgentLake\n"
            "  AGENTLAKE_API_KEY    Fallback API key (if MCP_SERVER_API_KEY not set)\n"
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="sse",
        help="Transport protocol (default: sse)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="SSE server bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8002,
        help="SSE server port (default: 8002)",
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        asyncio.run(run_stdio())
    else:
        asyncio.run(run_sse(host=args.host, port=args.port))


if __name__ == "__main__":
    main()

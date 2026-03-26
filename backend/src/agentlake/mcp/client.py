"""HTTP client wrapper for the AgentLake REST API.

Used by the MCP server to proxy tool calls, resource reads, and prompt
data through the AgentLake API.  All methods return parsed JSON dicts
and raise ``AgentLakeAPIError`` on non-2xx responses.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class AgentLakeAPIError(Exception):
    """Raised when the AgentLake API returns a non-success status."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"AgentLake API error {status_code}: {detail}")


class AgentLakeClient:
    """Async HTTP client for the AgentLake REST API.

    Args:
        base_url: Root URL of the AgentLake API (e.g. ``http://localhost:8000``).
        api_key: API key sent via the ``X-API-Key`` header.
        timeout: Default request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP request and return the JSON response body.

        Raises:
            AgentLakeAPIError: If the response status is not 2xx.
        """
        logger.debug(
            "mcp_client_request",
            method=method,
            path=path,
            params=params,
        )
        response = await self._client.request(
            method,
            path,
            params=params,
            json=json,
            data=data,
            files=files,
        )
        if response.status_code >= 400:
            detail = response.text
            try:
                body = response.json()
                detail = body.get("detail", body.get("title", detail))
            except Exception:
                pass
            raise AgentLakeAPIError(response.status_code, str(detail))
        return response.json()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover(self) -> dict[str, Any]:
        """GET /api/v1/discover -- overview of the data lake."""
        return await self._request("GET", "/api/v1/discover")

    # ------------------------------------------------------------------
    # Search & Query
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        search_type: str = "hybrid",
        limit: int = 10,
        category: str | None = None,
        tags: list[str] | None = None,
        entities: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """GET /api/v1/query/search -- search processed documents."""
        params: dict[str, Any] = {
            "q": query,
            "search_type": search_type,
            "limit": limit,
        }
        if category:
            params["category"] = category
        if tags:
            params["tags"] = ",".join(tags)
        if entities:
            params["entities"] = entities
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/api/v1/query/search", params=params)

    async def get_document(self, document_id: str) -> dict[str, Any]:
        """GET /api/v1/query/documents/{id} -- full processed document."""
        return await self._request("GET", f"/api/v1/query/documents/{document_id}")

    async def get_citations(self, document_id: str) -> dict[str, Any]:
        """GET /api/v1/query/documents/{id}/citations -- citation list."""
        return await self._request(
            "GET", f"/api/v1/query/documents/{document_id}/citations"
        )

    async def edit_document(
        self,
        document_id: str,
        body_markdown: str,
        justification: str,
    ) -> dict[str, Any]:
        """PUT /api/v1/query/documents/{id} -- edit document content."""
        return await self._request(
            "PUT",
            f"/api/v1/query/documents/{document_id}",
            json={
                "body_markdown": body_markdown,
                "justification": justification,
            },
        )

    async def list_documents(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """GET /api/v1/query/documents -- paginated document list."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/api/v1/query/documents", params=params)

    # ------------------------------------------------------------------
    # Vault (file management)
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        file_path: str,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/vault/upload -- upload a local file.

        Reads the file from the local filesystem, determines its MIME type,
        and sends it as a multipart upload.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        file_bytes = path.read_bytes()

        files_payload: list[tuple[str, tuple[str, bytes, str]]] = [
            ("file", (path.name, file_bytes, content_type)),
        ]

        data_payload: dict[str, Any] = {}
        if tags:
            data_payload["tags"] = ",".join(tags)

        return await self._request(
            "POST",
            "/api/v1/vault/upload",
            files=files_payload,
            data=data_payload if data_payload else None,
        )

    async def get_file(self, file_id: str) -> dict[str, Any]:
        """GET /api/v1/vault/files/{id} -- file metadata."""
        return await self._request("GET", f"/api/v1/vault/files/{file_id}")

    async def list_tags(self) -> dict[str, Any]:
        """GET /api/v1/vault/tags -- all tags with counts."""
        return await self._request("GET", "/api/v1/vault/tags")

    # ------------------------------------------------------------------
    # Graph
    # ------------------------------------------------------------------

    async def graph_search(
        self,
        query: str,
        entity_type: str | None = None,
    ) -> dict[str, Any]:
        """GET /api/v1/graph/search -- search entities by name."""
        params: dict[str, Any] = {"q": query}
        if entity_type:
            params["type"] = entity_type
        return await self._request("GET", "/api/v1/graph/search", params=params)

    async def get_entity_neighbors(
        self,
        entity_id: str,
        depth: int = 1,
    ) -> dict[str, Any]:
        """GET /api/v1/graph/entity/{id}/neighbors -- entity relationships."""
        return await self._request(
            "GET",
            f"/api/v1/graph/entity/{entity_id}/neighbors",
            params={"depth": depth},
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

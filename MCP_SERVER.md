# Feature Spec: MCP Server

## Overview

AgentLake exposes itself as a **Model Context Protocol (MCP)** server. This allows Claude Desktop, Claude Code, and any MCP-compatible client to directly search, browse, upload, and manage data in AgentLake without custom API integration.

The MCP server runs as a separate process/container alongside the API server. It wraps the existing REST API endpoints as MCP tools.

---

## MCP Server Architecture

```
Claude Desktop / Claude Code / Any MCP Client
    │
    ├── MCP Protocol (stdio or SSE transport)
    │
    ▼
[AgentLake MCP Server]
    │
    ├── Translates MCP tool calls → REST API calls
    │
    ▼
[AgentLake API Server (existing)]
```

The MCP server is a thin translation layer. It does NOT contain business logic — it calls the existing REST API for everything. This ensures:
- Single source of truth for all operations
- Auth, rate limiting, logging all go through the standard path
- No MCP-specific data paths that bypass the token ledger

---

## Transport

Two transport modes:

1. **stdio** — for Claude Code and local integrations (process spawned by the client)
2. **SSE (HTTP)** — for remote/networked integrations (always-running server)

The SSE transport is served at:

```
http://agentlake-host:8002/mcp/sse
```

---

## MCP Tools Exposed

### 1. `agentlake_search`

Search the processed data store.

```json
{
  "name": "agentlake_search",
  "description": "Search the AgentLake data lake for processed documents. Supports keyword, semantic, and hybrid search with filtering by tags, categories, entities, and date ranges.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Natural language search query"},
      "search_type": {"type": "string", "enum": ["hybrid", "keyword", "semantic"], "default": "hybrid"},
      "category": {"type": "string", "description": "Filter by category (technical, business, operational, research, communication, reference)"},
      "tags": {"type": "string", "description": "Comma-separated tag filter"},
      "entities": {"type": "string", "description": "Comma-separated entity names to filter by"},
      "date_from": {"type": "string", "description": "ISO date string, filter documents after this date"},
      "date_to": {"type": "string", "description": "ISO date string, filter documents before this date"},
      "limit": {"type": "integer", "default": 10, "description": "Max results to return"}
    },
    "required": ["query"]
  }
}
```

### 2. `agentlake_get_document`

Retrieve a full processed document by ID.

```json
{
  "name": "agentlake_get_document",
  "description": "Get a complete processed document from AgentLake including its markdown body, metadata, entities, and citations.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "document_id": {"type": "string", "description": "UUID of the processed document"}
    },
    "required": ["document_id"]
  }
}
```

### 3. `agentlake_get_citations`

Get citations for a document (trace claims back to raw sources).

```json
{
  "name": "agentlake_get_citations",
  "description": "Get all citations for a processed document. Each citation links a claim in the document back to the exact location in the raw source file.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "document_id": {"type": "string", "description": "UUID of the processed document"}
    },
    "required": ["document_id"]
  }
}
```

### 4. `agentlake_discover`

Discover what data is available in the lake.

```json
{
  "name": "agentlake_discover",
  "description": "Get an overview of the AgentLake data lake: total files, documents, available categories, top tags, and entity counts. Use this first to understand what data is available before searching.",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

### 5. `agentlake_upload`

Upload a file to the data lake.

```json
{
  "name": "agentlake_upload",
  "description": "Upload a file to AgentLake for processing. The file will be stored in the raw vault and automatically processed through the LLM pipeline to create a searchable, cited summary.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {"type": "string", "description": "Local file path to upload"},
      "tags": {"type": "string", "description": "Comma-separated tags to assign to the file"}
    },
    "required": ["file_path"]
  }
}
```

### 6. `agentlake_list_tags`

List all tags with document counts.

```json
{
  "name": "agentlake_list_tags",
  "description": "List all tags in AgentLake with their descriptions and document counts.",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

### 7. `agentlake_graph_explore`

Explore entity relationships in the knowledge graph.

```json
{
  "name": "agentlake_graph_explore",
  "description": "Explore entity relationships in the AgentLake knowledge graph. Find how entities (people, organizations, products, technologies) are connected through documents.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "entity_name": {"type": "string", "description": "Name of the entity to explore"},
      "depth": {"type": "integer", "default": 2, "description": "How many relationship hops to traverse (1-3)"},
      "relationship_types": {"type": "string", "description": "Comma-separated relationship types to filter (partners_with, develops, uses, etc.)"}
    },
    "required": ["entity_name"]
  }
}
```

### 8. `agentlake_edit_document`

Edit a processed document.

```json
{
  "name": "agentlake_edit_document",
  "description": "Edit the markdown body of a processed document. Creates a version history entry and diff log. Use this to correct errors or add context to processed documents.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "document_id": {"type": "string", "description": "UUID of the document to edit"},
      "body_markdown": {"type": "string", "description": "Updated markdown body"},
      "justification": {"type": "string", "description": "Reason for the edit", "default": "Agent Edit"}
    },
    "required": ["document_id", "body_markdown"]
  }
}
```

---

## MCP Resources

The server exposes **MCP resources** for browsable access:

### Resource: Document Collection

```
agentlake://documents
```

Returns a paginated list of all processed documents. Supports filtering via URI parameters.

### Resource: Individual Document

```
agentlake://documents/{id}
```

Returns the full processed document markdown as a resource.

### Resource: Raw File

```
agentlake://vault/{file_id}
```

Returns raw file metadata and a download URI.

---

## MCP Prompts

Pre-built prompts for common agent workflows:

### `research_topic`

```json
{
  "name": "research_topic",
  "description": "Research a topic across all documents in the data lake, synthesize findings with citations",
  "arguments": [
    {"name": "topic", "description": "The topic to research", "required": true}
  ]
}
```

Generates a system prompt that instructs Claude to:
1. Call `agentlake_discover` to understand available data
2. Call `agentlake_search` with the topic
3. Call `agentlake_get_document` for top results
4. Call `agentlake_get_citations` to verify claims
5. Synthesize a report with proper attribution

### `entity_briefing`

```json
{
  "name": "entity_briefing",
  "description": "Generate a briefing about an entity (person, company, product) based on all available data",
  "arguments": [
    {"name": "entity_name", "description": "Name of the entity", "required": true}
  ]
}
```

---

## Container & Configuration

### Docker Compose Entry

```yaml
mcp-server:
  build:
    context: ./backend
    dockerfile: Dockerfile
    target: runtime
  command: python -m agentlake.mcp.server --transport sse --port 8002
  environment:
    - AGENTLAKE_API_URL=http://api:8000
    - AGENTLAKE_API_KEY=${MCP_SERVER_API_KEY}
  ports:
    - "8002:8002"
  depends_on:
    - api
```

### Environment Variables

```bash
# MCP Server
MCP_SERVER_PORT=8002
MCP_SERVER_TRANSPORT=sse        # or "stdio" for local use
AGENTLAKE_API_URL=http://api:8000
AGENTLAKE_API_KEY=<api-key-with-agent-role>
```

---

## Project Structure

```
backend/src/agentlake/mcp/
├── __init__.py
├── server.py           # MCP server entry point (stdio + SSE transports)
├── tools.py            # Tool implementations (wrappers around REST API calls)
├── resources.py        # MCP resource definitions
└── prompts.py          # Pre-built MCP prompts
```

---

## Testing

- **Unit:** Each tool correctly translates MCP input → REST API call → MCP output
- **Integration:** Full MCP round-trip: connect → call tool → get result
- **Integration:** Verify MCP tool auth passes through to API (API key validation)
- **Compatibility:** Test with Claude Desktop MCP client
- **Compatibility:** Test with Claude Code MCP client

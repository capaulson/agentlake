---
name: agentlake
description: >
  Search, retrieve, upload, and manage data in an AgentLake instance.
  Use this skill when the user references stored documents, partner data,
  meeting notes, research, technical documentation, or any data that lives
  in AgentLake. Also use when the user asks to upload files, check processing
  status, explore entity relationships, or search for information across
  their data lake.
triggers:
  - "search agentlake"
  - "find in the data lake"
  - "what do we have on"
  - "check the vault"
  - "upload this to agentlake"
  - "look up the document"
  - "who is connected to"
  - "what's related to"
  - "explore entities"
  - "data lake search"
  - "partner documents"
  - "meeting notes about"
  - "technical spec for"
  - "agentlake"
---

# AgentLake Data Lake Integration

## Overview

AgentLake is a distributed data lake that stores raw files and LLM-processed summaries with full citation traceability. This skill connects Claude Code to an AgentLake instance for searching, retrieving, and managing data.

## Configuration

### Option 1: MCP Server (Preferred)

Configure the AgentLake MCP server in `.claude/settings.json` or Claude Desktop config:

```json
{
  "mcpServers": {
    "agentlake": {
      "command": "python",
      "args": ["-m", "agentlake.mcp.server", "--transport", "stdio"]
    }
  }
}
```

Or for remote SSE connections:

```json
{
  "mcpServers": {
    "agentlake": {
      "url": "http://localhost:8002/sse"
    }
  }
}
```

### Option 2: Direct REST API

Set environment variables:

```bash
AGENTLAKE_URL=http://localhost:8000      # AgentLake API base URL
AGENTLAKE_API_KEY=al-your-api-key        # API key with 'agent' role
```

## Available Operations

### Search

Search for processed documents using natural language queries.

```bash
curl -s "${AGENTLAKE_URL}/api/v1/query/search?q=YOUR_QUERY&search_type=hybrid&limit=10" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}"
```

**Search types:** `hybrid` (default, best results), `keyword` (exact terms), `semantic` (meaning-based)

**Filtering:** Add `category=technical`, `tags=partner:siemens`, `entities=Isaac+Sim`, `date_from=2026-01-01`

### Get Document

Retrieve a full processed document with markdown body, metadata, and citations.

```bash
curl -s "${AGENTLAKE_URL}/api/v1/query/documents/DOCUMENT_ID" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}"
```

### Get Citations

Verify claims by fetching citation links back to original source data.

```bash
curl -s "${AGENTLAKE_URL}/api/v1/query/documents/DOCUMENT_ID/citations" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}"
```

### Upload File

Add a file to the data lake for processing.

```bash
curl -X POST "${AGENTLAKE_URL}/api/v1/vault/upload" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}" \
  -F "file=@/path/to/file" \
  -F "tags=robotics,partner:siemens"
```

### Discover

Get an overview of available data (counts, categories, tags, entity types).

```bash
curl -s "${AGENTLAKE_URL}/api/v1/discover" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}"
```

### Explore Entity Graph

Search for entities and explore their relationships.

```bash
# Search for an entity
curl -s "${AGENTLAKE_URL}/api/v1/graph/search?q=ENTITY_NAME&type=organization" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}"

# Get entity neighbors
curl -s "${AGENTLAKE_URL}/api/v1/graph/entity/ENTITY_ID/neighbors?depth=2" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}"
```

### List Tags

List all tags with file counts.

```bash
curl -s "${AGENTLAKE_URL}/api/v1/vault/tags" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}"
```

### Edit Document

Correct or enhance a processed document (creates version history with diff tracking).

```bash
curl -X PUT "${AGENTLAKE_URL}/api/v1/query/documents/DOCUMENT_ID" \
  -H "X-API-Key: ${AGENTLAKE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"body_markdown": "updated content...", "justification": "Corrected entity name"}'
```

## Workflow Patterns

### Research a Topic

1. `GET /api/v1/discover` -- understand what data is available
2. `GET /api/v1/query/search?q={topic}&limit=10` -- find relevant documents
3. `GET /api/v1/query/documents/{id}` -- read the most relevant ones
4. `GET /api/v1/query/documents/{id}/citations` -- verify specific claims
5. Synthesize findings with proper attribution to source documents

### Entity Briefing

1. `GET /api/v1/graph/search?q={entity_name}` -- find the entity
2. `GET /api/v1/graph/entity/{id}/neighbors?depth=2` -- map relationships
3. `GET /api/v1/query/search?q={entity_name}` -- find all mentions
4. `GET /api/v1/query/documents/{id}` -- read relevant documents
5. Compile a briefing with overview, relationships, timeline, and citations

### Upload and Track

1. `POST /api/v1/vault/upload` -- upload the file with tags
2. `GET /api/v1/vault/files/{id}` -- poll status until `status: "processed"`
3. `GET /api/v1/query/search?q=...` -- search for the newly processed content

## Error Handling

- **401:** API key is invalid or missing. Check `AGENTLAKE_API_KEY`.
- **404:** Document or file not found. Verify the ID.
- **429:** Rate limit exceeded. Wait and retry.
- **502:** LLM gateway error (processing may be delayed). The file is queued for retry.

## Notes

- All timestamps are UTC ISO 8601
- All IDs are UUIDs
- Pagination uses cursor-based pagination (`cursor` parameter)
- Maximum upload file size: 100MB
- Processing typically takes 15-60 seconds per file depending on size

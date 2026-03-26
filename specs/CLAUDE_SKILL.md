# AgentLake Skill for Claude Code

## SKILL.md

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
  - "partner documents"
  - "meeting notes about"
  - "technical spec for"
---

## Overview

AgentLake is a distributed data lake that stores raw files and LLM-processed summaries with full citation traceability. This skill connects Claude Code to an AgentLake instance for searching, retrieving, and managing data.

## Configuration

Before using this skill, ensure these environment variables are set in the project:

```bash
AGENTLAKE_URL=http://localhost:8000      # AgentLake API base URL
AGENTLAKE_API_KEY=al-your-api-key        # API key with 'agent' role
```

Or connect via MCP (preferred):

```json
// In .claude/settings.json or Claude Desktop config
{
  "mcpServers": {
    "agentlake": {
      "url": "http://localhost:8002/mcp/sse"
    }
  }
}
```

## Available Operations

### 1. Search the Data Lake

Search for processed documents using natural language queries.

```bash
# Via curl (REST API)
curl -s -H "X-API-Key: $AGENTLAKE_API_KEY" \
  "$AGENTLAKE_URL/api/v1/query/search?q=robot+arm+precision&limit=5" | python -m json.tool
```

**When to search:** Whenever the user asks about information that might be stored — partner updates, meeting notes, technical specs, research findings, competitive analysis, financial data, etc.

**Search types:**
- `hybrid` (default) — combines keyword + semantic for best results
- `keyword` — exact term matching, good for model numbers, specific names
- `semantic` — meaning-based, good for conceptual queries

**Filtering:** Add `category=technical`, `tags=partner:siemens`, `entities=Isaac+Sim`, `date_from=2026-01-01`

### 2. Retrieve a Document

Get the full processed document including its markdown body, metadata, and citation links.

```bash
curl -s -H "X-API-Key: $AGENTLAKE_API_KEY" \
  "$AGENTLAKE_URL/api/v1/query/documents/{document_id}" | python -m json.tool
```

### 3. Verify Citations

Every claim in a processed document has a citation linking back to the raw source. Verify claims by following citations.

```bash
# Get citations for a document
curl -s -H "X-API-Key: $AGENTLAKE_API_KEY" \
  "$AGENTLAKE_URL/api/v1/query/documents/{document_id}/citations" | python -m json.tool

# Download the raw source file referenced by a citation
curl -s -H "X-API-Key: $AGENTLAKE_API_KEY" \
  "$AGENTLAKE_URL/api/v1/vault/files/{source_file_id}/download" -o source_file.pdf
```

### 4. Upload Files

Add files to the data lake for processing.

```bash
curl -X POST -H "X-API-Key: $AGENTLAKE_API_KEY" \
  -F "file=@/path/to/document.pdf" \
  -F "tags=robotics,partner:siemens" \
  "$AGENTLAKE_URL/api/v1/vault/upload"
```

### 5. Discover Available Data

Understand what's in the data lake before searching.

```bash
curl -s -H "X-API-Key: $AGENTLAKE_API_KEY" \
  "$AGENTLAKE_URL/api/v1/discover" | python -m json.tool
```

### 6. Explore Entity Graph

Explore how entities (people, organizations, products) are connected.

```bash
# Find entity and its connections
curl -s -H "X-API-Key: $AGENTLAKE_API_KEY" \
  "$AGENTLAKE_URL/api/v1/graph/entity/{entity_id}/neighbors?depth=2" | python -m json.tool

# Search for an entity by name
curl -s -H "X-API-Key: $AGENTLAKE_API_KEY" \
  "$AGENTLAKE_URL/api/v1/graph/search?q=siemens&type=organization" | python -m json.tool
```

### 7. Edit Documents

Correct or enhance processed documents. Creates a version history entry.

```bash
curl -X PUT -H "X-API-Key: $AGENTLAKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"body_markdown": "updated content...", "justification": "Agent correction: fixed entity name"}' \
  "$AGENTLAKE_URL/api/v1/query/documents/{document_id}"
```

## Workflow Patterns

### Pattern: Research a Topic

1. `GET /api/v1/discover` — understand what data is available
2. `GET /api/v1/query/search?q={topic}&limit=10` — find relevant documents
3. `GET /api/v1/query/documents/{id}` — read the most relevant ones
4. `GET /api/v1/query/documents/{id}/citations` — verify specific claims
5. Synthesize findings with proper attribution to source documents

### Pattern: Prepare for a Meeting

1. `GET /api/v1/query/search?q={partner_name}&tags=meeting-notes&limit=20` — find meeting history
2. `GET /api/v1/graph/search?q={partner_name}` — find the entity
3. `GET /api/v1/graph/entity/{id}/neighbors?depth=1` — see what they're connected to
4. Compile a briefing from the results

### Pattern: Upload and Track

1. `POST /api/v1/vault/upload` — upload the file with tags
2. `GET /api/v1/vault/files/{id}` — poll status until `status: "processed"`
3. `GET /api/v1/query/search?q=...` — search for the newly processed content

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

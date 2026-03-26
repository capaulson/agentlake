# AgentLake API Reference

## Complete Endpoint Documentation

**Base URL:** `http://localhost:8000` (development) or `https://agentlake.your-domain.com` (production)

**Authentication:** All endpoints require `X-API-Key` header unless noted.

**Content-Type:** `application/json` for all request/response bodies except file uploads (`multipart/form-data`).

**Pagination:** Cursor-based. Response `meta.cursor` value is passed as `?cursor=` on next request.

**Errors:** All errors use RFC 7807 Problem Details format.

---

## Discovery Endpoints

### GET `/api/v1/discover`

System overview for agent bootstrapping. **Call this first** to understand the data lake.

**Auth:** Required (any role)

**Response:**

```json
{
  "name": "AgentLake",
  "version": "1.0.0",
  "description": "Distributed agent-friendly data lake with LLM-processed documents and full citation traceability.",
  "capabilities": ["search", "upload", "download", "edit", "tag", "graph"],
  "data_summary": {
    "total_raw_files": 12453,
    "total_processed_documents": 11892,
    "categories": ["technical", "business", "operational", "research", "communication", "reference"],
    "top_tags": [{"name": "robotics", "count": 2341}],
    "entity_count": 1283,
    "last_updated": "2026-03-24T10:30:00Z"
  },
  "authentication": {"method": "API key", "header": "X-API-Key"}
}
```

### GET `/api/v1/discover/schema`

Returns the Common Data Ontology schema (category definitions, entity types, frontmatter fields).

### GET `/api/v1/discover/tags`

All tags with descriptions and file counts.

### GET `/api/v1/discover/categories`

All categories with document counts.

### GET `/api/v1/discover/stats`

Detailed system statistics.

### GET `/api/v1/health`

Health check. **Auth:** Not required.

---

## Vault Endpoints (Layer 1 — Raw Data)

### POST `/api/v1/vault/upload`

Upload one or more files.

**Auth:** `agent` or `admin` role

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | binary | yes | File to upload |
| `tags` | string | no | Comma-separated tags |

**Response:** `201 Created`

```json
{
  "id": "uuid",
  "filename": "report.pdf",
  "status": "pending",
  "tags": ["robotics", "research"],
  "processing_stream": "/api/v1/stream/processing/uuid"
}
```

### GET `/api/v1/vault/files`

List raw files with filtering.

| Param | Type | Description |
|-------|------|-------------|
| `tags` | string | Comma-separated tag filter |
| `status` | string | Filter by status (pending, processing, processed, error) |
| `content_type` | string | MIME type filter |
| `sort_by` | string | `created_at` (default), `size_bytes`, `filename` |
| `sort_order` | string | `desc` (default), `asc` |
| `limit` | int | Max results (default 20, max 100) |
| `cursor` | string | Pagination cursor |

### GET `/api/v1/vault/files/{id}`

Get file metadata.

### GET `/api/v1/vault/files/{id}/download`

Download the raw file. Returns the file bytes with appropriate Content-Type header.

### DELETE `/api/v1/vault/files/{id}`

Soft-delete a file. **Auth:** `editor` or `admin`.

### PUT `/api/v1/vault/files/{id}/tags`

Update tags on a file.

**Body:** `{"tags": ["tag1", "tag2"]}`

### GET `/api/v1/vault/tags`

List all tags with file counts.

### POST `/api/v1/vault/tags`

Create a new tag.

**Body:** `{"name": "new-tag", "description": "optional description"}`

### POST `/api/v1/vault/reprocess/{id}`

Re-trigger processing.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `incremental` | `incremental` or `full` |

---

## Query Endpoints (Layer 3 — Processed Data)

### GET `/api/v1/query/search`

Primary search endpoint. Returns ranked results with highlighted snippets.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | required | Natural language query |
| `search_type` | string | `hybrid` | `hybrid`, `keyword`, `semantic` |
| `category` | string | — | Filter by category |
| `tags` | string | — | Comma-separated tag filter |
| `entities` | string | — | Comma-separated entity names |
| `date_from` | string | — | ISO date, documents after this date |
| `date_to` | string | — | ISO date, documents before this date |
| `keyword_weight` | float | 0.4 | Keyword component weight (hybrid only) |
| `semantic_weight` | float | 0.6 | Semantic component weight (hybrid only) |
| `limit` | int | 20 | Max results (max 100) |
| `cursor` | string | — | Pagination cursor |

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "title": "Robot Arm Precision Testing",
      "summary": "Testing results showing 0.1mm repeatability...",
      "category": "technical",
      "subcategory": "test-results",
      "relevance_score": 0.94,
      "snippet": "...achieves <mark>0.1mm repeatability</mark> in structured...",
      "source_filename": "precision-test-report.pdf",
      "tags": ["robotics"],
      "entities": [{"name": "xArm", "type": "product"}],
      "processed_at": "2026-03-20T14:22:00Z"
    }
  ],
  "meta": {
    "total_results": 47,
    "cursor": "eyJvZmZzZXQiOjIwfQ==",
    "search_type": "hybrid",
    "query_time_ms": 142
  }
}
```

### GET `/api/v1/query/documents`

Browse documents with filtering and pagination. Same filter params as search (minus `q`).

### GET `/api/v1/query/documents/{id}`

Full processed document.

```json
{
  "data": {
    "id": "uuid",
    "source_file_id": "uuid",
    "title": "...",
    "summary": "...",
    "category": "technical",
    "subcategory": "test-results",
    "body_markdown": "# Full markdown body with [1] citations...",
    "frontmatter": { "...full ontology frontmatter..." },
    "entities": [{"name": "xArm", "type": "product"}],
    "tags": ["robotics"],
    "version": 3,
    "created_at": "2026-03-20T14:22:00Z",
    "updated_at": "2026-03-24T09:15:00Z"
  }
}
```

### GET `/api/v1/query/documents/{id}/history`

Version history with diff summaries.

### PUT `/api/v1/query/documents/{id}`

Edit a processed document. **Auth:** `editor` or `admin`.

**Body:**

```json
{
  "body_markdown": "updated markdown content...",
  "justification": "Human Edit: corrected entity name"
}
```

Creates a version history entry, diff log, and re-generates embeddings.

### GET `/api/v1/query/documents/{id}/citations`

All citations for a document.

```json
{
  "data": [
    {
      "index": 1,
      "source_file_id": "uuid",
      "source_filename": "precision-test-report.pdf",
      "chunk_index": 3,
      "source_locator": "page 7, section 2.3",
      "quote_snippet": "The robot arm achieves 0.1mm repeatab...",
      "download_url": "/api/v1/vault/files/uuid/download"
    }
  ]
}
```

### GET `/api/v1/query/stats`

Collection statistics.

### GET `/api/v1/query/categories`

Categories with counts.

### GET `/api/v1/query/entities`

All extracted entities with mention counts.

---

## Graph Endpoints (Entity Relationships)

### GET `/api/v1/graph/search`

Search for entities by name or type.

| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Entity name search |
| `type` | string | Filter by entity type |
| `limit` | int | Max results (default 20) |

### GET `/api/v1/graph/entity/{id}`

Get entity with all its relationships.

### GET `/api/v1/graph/entity/{id}/neighbors`

Traverse the graph from an entity.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `depth` | int | 2 | Hops to traverse (1-3) |
| `relationship_types` | string | — | Comma-separated filter |
| `min_weight` | int | 1 | Minimum edge weight |

### GET `/api/v1/graph/path`

Shortest path between two entities.

| Param | Type | Description |
|-------|------|-------------|
| `from` | string | Source entity ID |
| `to` | string | Target entity ID |

### GET `/api/v1/graph/entity/{id}/documents`

Documents that mention this entity.

### GET `/api/v1/graph/relationships`

List relationships filtered by type.

### GET `/api/v1/graph/stats`

Graph statistics (node count, edge count, top entity types, top relationship types).

---

## Streaming Endpoints

### GET `/api/v1/stream/processing/{file_id}`

SSE stream of processing progress. **Accept:** `text/event-stream`.

Events: `stage_update`, `complete`, `error`.

### GET `/api/v1/stream/search`

SSE stream of search results. Same params as `/api/v1/query/search`. **Accept:** `text/event-stream`.

Events: `result`, `meta`, `done`.

### WS `/ws/dashboard`

WebSocket for live dashboard stats. Auth via `?token=` query param.

---

## LLM Gateway Endpoints (Layer 4B — Internal Only)

These endpoints are internal to the AgentLake cluster. External clients do NOT call these directly.

### POST `/api/v1/llm/complete`

**Auth:** `X-Service-Token` header (internal)

### POST `/api/v1/llm/embed`

**Auth:** `X-Service-Token` header (internal)

### GET `/api/v1/llm/usage`

Token usage statistics. Accessible via Admin API at `/api/v1/admin/llm-usage`.

### GET `/api/v1/llm/providers`

List enabled LLM providers.

---

## Admin Endpoints

**Auth:** `admin` role required for all admin endpoints.

### GET `/api/v1/admin/api-keys`

List API keys.

### POST `/api/v1/admin/api-keys`

Create a new API key.

**Body:** `{"name": "my-agent", "role": "agent", "rate_limit": 100}`

### DELETE `/api/v1/admin/api-keys/{id}`

Revoke an API key.

### GET `/api/v1/admin/llm-usage`

LLM token usage dashboard data with breakdowns by provider, model, service, and time.

### GET `/api/v1/admin/queue-status`

Processing queue depths.

---

## Rate Limiting

All responses include rate limit headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1711282800
```

Default: 100 requests/minute per API key. Configurable per key.

---

## Error Format

All errors use RFC 7807:

```json
{
  "type": "https://agentlake.dev/errors/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "No document with ID abc123.",
  "instance": "/api/v1/query/documents/abc123"
}
```

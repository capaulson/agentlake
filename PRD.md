# Product Requirements Document: AgentLake

## Distributed Agent-Friendly Data Lake

**Version:** 1.0.0
**Status:** Draft
**Author:** Chris (NVIDIA DevRel – Robotics & Physical AI)
**Date:** 2026-03-24

---

## 1. Executive Summary

AgentLake is a distributed, containerized data lake purpose-built for AI agent workflows. It replaces local Obsidian-based markdown file storage with a scalable, multi-layer system that ingests raw unstructured data, processes it through an agentic pipeline into queryable markdown with full citation traceability, and exposes the results through a high-performance API and modern React UI.

The system is designed around a single invariant: **every piece of processed data must trace back to its raw source with citation links, and every LLM call must pass through the centralized LLM gateway.**

### Problem Statement

Local markdown storage (Obsidian) works for a single user on a single machine but fails when:

- Multiple agents need concurrent read/write access
- Data volume exceeds what fits on a laptop
- Multiple users or services need shared access
- Provenance and traceability of AI-generated summaries is required
- Search performance over large corpora becomes critical

### Solution

A five-layer architecture deployed as Docker containers with externally mounted persistent storage, designed for single-node development and multi-node Kubernetes production.

---

## 2. System Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Layer 4A: API & React UI                   │
│  FastAPI REST endpoints  │  React/TypeScript dashboard        │
├──────────────────────────────────────────────────────────────┤
│              Layer 4B: LLM Gateway & Token Ledger             │
│  Central proxy for ALL LLM calls │ Usage logging │ Rate ctrl  │
├──────────────────────────────────────────────────────────────┤
│          Layer 3: Processed Data Store (QueryStore)           │
│  PostgreSQL + pgvector │ Full-text search │ Semantic search   │
├──────────────────────────────────────────────────────────────┤
│        Layer 2: Agentic Processing Pipeline (Distiller)       │
│  Celery workers │ Extract → Chunk → Summarize → Cite → Store │
├──────────────────────────────────────────────────────────────┤
│            Layer 1: Raw Data Store (Vault)                    │
│  MinIO (S3-compatible) │ PostgreSQL metadata │ Tag system     │
├──────────────────────────────────────────────────────────────┤
│          Layer 5: Infrastructure & Scaling                    │
│  Docker │ Docker Compose │ K8s manifests │ Persistent volumes │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Layer Specifications

### 3.1 Layer 1 — Raw Data Store (Vault)

**Purpose:** Ingest and store raw files in their original format with tag-based organization.

#### Supported File Types (Initial)

| Category | Extensions |
|----------|-----------|
| Documents | `.txt`, `.md`, `.pdf`, `.docx`, `.rtf` |
| Spreadsheets | `.xlsx`, `.xls`, `.csv`, `.tsv` |
| Presentations | `.pptx`, `.ppt` |
| Data | `.json`, `.yaml`, `.yml`, `.xml` |
| Web | `.html`, `.htm` |
| Images | `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp` |
| Code | `.py`, `.js`, `.ts`, `.go`, `.rs`, `.c`, `.cpp`, `.h`, `.java` |

#### Extensibility

New file types are added by implementing a `FileAdapter` interface:

```python
class FileAdapter(Protocol):
    supported_extensions: list[str]
    def extract_text(self, file_bytes: bytes, filename: str) -> ExtractedContent: ...
    def extract_metadata(self, file_bytes: bytes, filename: str) -> dict: ...
```

Adapters are registered in a central `AdapterRegistry` and auto-discovered at startup.

#### Storage Backend

- **Object Storage:** MinIO (S3-compatible API) for raw file blobs
- **Metadata DB:** PostgreSQL for file metadata, tags, and relationships

#### Data Model

```
File:
  id: UUID (primary key)
  filename: str
  original_filename: str
  content_type: str (MIME type)
  size_bytes: int
  sha256_hash: str (deduplication)
  storage_key: str (MinIO object key)
  uploaded_at: datetime
  uploaded_by: str
  status: enum(pending, processing, processed, error)

Tag:
  id: UUID
  name: str (unique, lowercase, slugified)
  description: str (optional)
  created_at: datetime

FileTag: (junction table)
  file_id: UUID (FK → File)
  tag_id: UUID (FK → Tag)
  assigned_at: datetime
  assigned_by: str
```

#### Tag System Requirements

- Tags are case-insensitive, stored lowercase
- Files may have zero or more tags
- Tags are assigned at upload time and can be modified after
- Reserved tag namespace: `system:*` for internal tags (e.g., `system:processing`, `system:error`)
- Example user tags: `partner:siemens`, `internal-only`, `documentation`, `meeting-notes`, `robotics`

#### API Endpoints (Layer 1)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/vault/upload` | Upload file(s) with tags |
| GET | `/api/v1/vault/files` | List files with filtering/pagination |
| GET | `/api/v1/vault/files/{id}` | Get file metadata |
| GET | `/api/v1/vault/files/{id}/download` | Download raw file |
| DELETE | `/api/v1/vault/files/{id}` | Soft-delete a file |
| PUT | `/api/v1/vault/files/{id}/tags` | Update tags on a file |
| GET | `/api/v1/vault/tags` | List all tags with file counts |
| POST | `/api/v1/vault/tags` | Create a new tag |
| POST | `/api/v1/vault/reprocess/{id}` | Re-trigger processing |

---

### 3.2 Layer 2 — Agentic Processing Pipeline (Distiller)

**Purpose:** Extract, understand, summarize, and cite raw data into structured markdown.

#### Processing Pipeline Stages

```
Raw File → [Extract] → [Chunk] → [Summarize] → [Cite] → [Ontology Map] → [Store]
```

**Stage 1: Extract**
- Use the appropriate `FileAdapter` to extract raw text and structural metadata
- Preserve section boundaries, headings, table structure, list hierarchy
- For images: generate alt-text descriptions via LLM (through Layer 4B)
- Output: `ExtractedContent` object with text blocks and structural markers

**Stage 2: Chunk**
- Split extracted content into semantically meaningful chunks
- Chunking strategy: paragraph-aware with configurable max token size (default: 1024 tokens)
- Each chunk retains a `source_locator` (page number, section heading, cell range, slide number)
- Output: list of `Chunk` objects with position metadata

**Stage 3: Summarize**
- Each chunk is summarized via LLM call (through Layer 4B)
- The LLM produces a structured summary following the common ontology (see below)
- Multiple chunks from the same file are also rolled up into a file-level summary
- Output: `Summary` objects at chunk-level and file-level

**Stage 4: Cite**
- Every claim in a summary is linked back to its source chunk(s)
- Citation format: `[Source: {file_id}#{chunk_index} | {source_locator}]`
- Citations are embedded as markdown links that resolve through the API:
  `[1](/api/v1/vault/files/{file_id}/download#chunk={chunk_index})`
- Output: Summary markdown with inline citation links

**Stage 5: Ontology Mapping**
- Apply the Common Data Ontology (see section 3.2.1) to classify and tag the processed data
- Assign category, subcategory, entity references, temporal markers
- Output: Ontology metadata attached to processed document

**Stage 6: Store**
- Write the final markdown document to Layer 3
- Generate and store embeddings (via Layer 4B) for vector search
- Index full text for keyword search
- Record the processing diff log (see section 3.2.2)

#### 3.2.1 Common Data Ontology

All processed data conforms to this frontmatter schema (YAML in markdown):

```yaml
---
id: "uuid"
source_file_id: "uuid"
source_filename: "original.pdf"
title: "Human-readable title"
summary: "One-paragraph executive summary"
category: "technical | business | operational | research | communication | reference"
subcategory: "string (free-form, LLM-assigned)"
entities:
  - name: "Siemens"
    type: "organization"
  - name: "Isaac Sim"
    type: "product"
  - name: "Chris"
    type: "person"
tags:
  - "robotics"
  - "partner:siemens"
temporal:
  document_date: "2026-03-15"
  date_range_start: "2026-Q1"
  date_range_end: "2026-Q2"
confidence_score: 0.87
processing_version: "1.0.0"
processed_at: "2026-03-24T10:30:00Z"
citations:
  - index: 1
    source_file_id: "uuid"
    chunk_index: 3
    source_locator: "page 7, section 2.3"
    quote_snippet: "first 50 chars of source text..."
---

# Document Title

Processed markdown body with inline citations [1], [2], etc.
```

#### 3.2.2 Diff / Change Log

Every transformation produces a diff record:

```
DiffLog:
  id: UUID
  document_id: UUID (FK → ProcessedDocument)
  source_file_id: UUID (FK → File)
  diff_type: enum(initial_processing, reprocessing, human_edit, agent_edit)
  before_text: text (null for initial processing)
  after_text: text
  justification: str
  created_at: datetime
  created_by: str
```

For initial processing, `justification` is "Automated processing from raw file {filename}".
For human edits via UI, `justification` is "Human Edit" plus an optional user-provided note.
For reprocessing, `justification` is "Reprocessing triggered: {reason}".

#### Worker Infrastructure

- **Queue:** Redis as message broker
- **Workers:** Celery workers, horizontally scalable
- **Concurrency:** Configurable workers per container (default: 4)
- **Retry policy:** 3 retries with exponential backoff (10s, 60s, 300s)
- **Dead letter queue:** Failed jobs moved to DLQ for manual inspection
- **Priority queues:** `high` (reprocessing), `default` (new uploads), `low` (bulk imports)

---

### 3.3 Layer 3 — Processed Data Store (QueryStore)

**Purpose:** Store, index, and serve processed markdown documents for fast retrieval.

#### Storage

- **PostgreSQL** with `pgvector` extension for vector similarity search
- Processed markdown stored as text columns with JSONB metadata
- Embeddings stored as `vector(1536)` columns (configurable dimension)

#### Data Model

```
ProcessedDocument:
  id: UUID (primary key)
  source_file_id: UUID (FK → File)
  title: str
  summary: str
  category: str
  subcategory: str
  body_markdown: text
  frontmatter: JSONB
  entities: JSONB (array of {name, type})
  embedding: vector(1536)
  version: int (incremented on edit)
  created_at: datetime
  updated_at: datetime
  is_current: bool (for versioning)

DocumentChunk:
  id: UUID
  document_id: UUID (FK → ProcessedDocument)
  chunk_index: int
  content: text
  embedding: vector(1536)
  source_locator: str
  token_count: int

Citation:
  id: UUID
  document_id: UUID (FK → ProcessedDocument)
  citation_index: int
  source_file_id: UUID (FK → File)
  chunk_index: int
  source_locator: str
  quote_snippet: str
```

#### Search Capabilities

**Full-Text Search (Keyword)**
- PostgreSQL `tsvector`/`tsquery` with ranking
- Support for: exact phrase, boolean operators, prefix matching
- Weighted ranking: title (A) > summary (B) > body (C) > entities (D)
- Response time target: < 100ms for 1M documents

**Semantic Search (Vector)**
- pgvector `<=>` cosine distance operator
- HNSW index for approximate nearest neighbor
- Query embedding generated through Layer 4B
- Response time target: < 200ms for 1M documents

**Hybrid Search**
- Combine full-text and semantic scores with configurable weighting
- Default: 0.4 keyword + 0.6 semantic
- Reciprocal Rank Fusion (RRF) for score combination

**Filtered Search**
- All searches support filtering by: tags, category, subcategory, entities, date range, source file type
- Filters applied before search scoring for performance

#### API Endpoints (Layer 3)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/query/search` | Hybrid search with filters |
| GET | `/api/v1/query/documents` | List/browse documents with pagination |
| GET | `/api/v1/query/documents/{id}` | Get full processed document |
| GET | `/api/v1/query/documents/{id}/history` | Version history |
| PUT | `/api/v1/query/documents/{id}` | Edit processed document (creates diff log) |
| GET | `/api/v1/query/documents/{id}/citations` | Get all citations for a document |
| GET | `/api/v1/query/stats` | Collection statistics |
| GET | `/api/v1/query/categories` | List categories with counts |
| GET | `/api/v1/query/entities` | List extracted entities |

---

### 3.4 Layer 4A — API & React UI

**Purpose:** External interface for humans and AI agents.

#### API Design Principles

- RESTful with consistent resource naming
- JSON request/response bodies
- OpenAPI 3.1 spec auto-generated from FastAPI
- API key authentication for agents; session auth for UI
- Rate limiting per API key (configurable, default 100 req/min)
- All responses include request ID for tracing
- Pagination: cursor-based for lists, with `limit` and `cursor` parameters
- Error responses follow RFC 7807 (Problem Details)

#### Agent Discovery Endpoints

These endpoints allow external AI agents to understand and navigate the data:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/discover` | System description, capabilities, data summary |
| GET | `/api/v1/discover/schema` | Data ontology schema definition |
| GET | `/api/v1/discover/tags` | All tags with descriptions and counts |
| GET | `/api/v1/discover/categories` | All categories with descriptions |
| GET | `/api/v1/discover/stats` | System-wide statistics |
| GET | `/api/v1/health` | Health check |
| GET | `/openapi.json` | OpenAPI spec |

The `/api/v1/discover` endpoint returns a structured description designed for LLM consumption:

```json
{
  "name": "AgentLake",
  "version": "1.0.0",
  "description": "Distributed agent-friendly data lake...",
  "capabilities": ["search", "upload", "download", "edit", "tag"],
  "data_summary": {
    "total_raw_files": 12453,
    "total_processed_documents": 11892,
    "categories": ["technical", "business", ...],
    "tag_count": 47,
    "entity_count": 1283
  },
  "endpoints": { ... },
  "authentication": "API key via X-API-Key header"
}
```

#### React UI Requirements

**Technology Stack:**
- React 18+ with TypeScript
- Vite build tooling
- TailwindCSS for styling
- Tanstack Query for data fetching
- Tanstack Router for routing
- Zustand for state management

**Pages and Views:**

1. **Dashboard** (`/`)
   - System health overview
   - Recent uploads and processing status
   - Quick search bar
   - Statistics cards (total files, processed docs, storage used, LLM tokens today)

2. **Search** (`/search`)
   - Full search interface with type-ahead
   - Filter sidebar (tags, categories, date range, entities, file type)
   - Results with highlighted snippets
   - Toggle between keyword, semantic, and hybrid search

3. **Document Viewer** (`/documents/{id}`)
   - Rendered markdown with syntax highlighting
   - Citation links that expand to show source context
   - Side panel showing frontmatter metadata
   - Edit mode with markdown editor
   - Version history timeline
   - Link to download raw source file

4. **Upload** (`/upload`)
   - Drag-and-drop file upload (single and batch)
   - Tag assignment during upload (autocomplete from existing tags)
   - Upload progress with processing status tracking
   - File type validation

5. **Vault Browser** (`/vault`)
   - Browse raw files with tag filtering
   - File preview (text, images, PDF viewer)
   - Batch tag management
   - Processing status indicators

6. **Tags Manager** (`/tags`)
   - CRUD for tags
   - Tag usage statistics
   - Merge/rename tags

7. **Admin / Monitoring** (`/admin`)
   - LLM token usage dashboard (from Layer 4B)
   - Processing queue status
   - API key management
   - System configuration

**UI Design Requirements:**
- Dark mode default with light mode toggle
- Monospace-accented design (code-friendly aesthetic)
- Responsive layout (desktop-first, tablet-friendly)
- Keyboard shortcuts for power users
- Real-time updates via WebSocket for processing status

#### Edit Workflow

When a user edits a processed document through the UI:

1. UI sends PUT request with updated markdown body
2. Backend computes text diff between current and proposed version
3. Backend creates a `DiffLog` entry with:
   - `diff_type`: `human_edit`
   - `before_text`: current body
   - `after_text`: new body
   - `justification`: "Human Edit" + optional user note
4. Backend increments document version, sets old version `is_current = false`
5. Backend re-generates embedding for the updated document via Layer 4B
6. Response includes the new document with updated version number

---

### 3.5 Layer 4B — LLM Gateway & Token Ledger

**Purpose:** Centralized, provider-agnostic proxy for all LLM interactions with usage tracking.

#### Architecture

```
                                  ┌─────────────────┐
                                  │  Provider Config │ (YAML / env)
                                  │  ┌────────────┐  │
                                  │  │ anthropic   │  │
                                  │  │ openrouter  │  │
                                  │  │ ollama      │  │
                                  │  │ custom...   │  │
                                  │  └────────────┘  │
                                  └────────┬────────┘
                                           │ selects
                                           ▼
Any Internal Service ──→ LLM Gateway ──→ [Provider Adapter] ──→ Provider API
                              │
                              ▼
                         Token Ledger (PostgreSQL)
```

The gateway uses a **provider adapter pattern**. Each LLM provider implements a common `LLMProvider` interface. The gateway selects the adapter at runtime based on the model string or an explicit `provider` field in the request. Adding a new provider means writing one adapter class — zero changes to the gateway core, zero changes to any calling service.

#### Critical Invariant

**ALL LLM calls in the entire system MUST route through Layer 4B. No service may call an LLM provider directly.** This is enforced by:

1. ALL provider API keys (Anthropic, OpenRouter, etc.) are ONLY configured in the Layer 4B service
2. No other service has access to any LLM API keys
3. Internal services use the gateway's internal URL and an internal service token
4. Network policies (in K8s) block direct egress to all LLM provider domains from other services

#### Provider Adapter Interface

Every provider implements this protocol:

```python
class LLMProvider(Protocol):
    """Interface that every LLM provider adapter must implement."""

    provider_name: str  # e.g. "anthropic", "openrouter", "ollama"

    async def complete(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.3,
        system: str | None = None,
        **kwargs,
    ) -> ProviderResponse:
        """Send a chat completion request. Returns a normalized response."""
        ...

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...

    def list_models(self) -> list[ModelInfo]:
        """Return available models and their capabilities."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check provider connectivity and quota status."""
        ...

@dataclass
class ProviderResponse:
    """Normalized response from any provider."""
    content: str
    model: str
    provider: str  # which adapter handled it
    input_tokens: int
    output_tokens: int
    total_tokens: int
    raw_response: dict  # original provider response for debugging
```

#### Built-In Provider Adapters

**1. Anthropic Direct (`anthropic`)**

```python
class AnthropicProvider(LLMProvider):
    """Direct Anthropic Claude API access."""
    provider_name = "anthropic"
    # Uses: ANTHROPIC_API_KEY
    # Base URL: https://api.anthropic.com
    # Models: claude-opus-4-*, claude-sonnet-4-*, claude-haiku-4-*
    # Embeddings: delegated to configured embedding provider
```

**2. OpenRouter (`openrouter`)**

```python
class OpenRouterProvider(LLMProvider):
    """OpenRouter multi-model gateway."""
    provider_name = "openrouter"
    # Uses: OPENROUTER_API_KEY
    # Base URL: https://openrouter.ai/api/v1
    # Models: any model on OpenRouter (anthropic/claude-sonnet-4,
    #         google/gemini-2.5-pro, meta-llama/llama-4-*, etc.)
    # Translates to/from OpenAI-compatible chat format
    # Embeddings: via OpenRouter embedding models or fallback provider
```

**3. OpenAI-Compatible (`openai_compat`)**

```python
class OpenAICompatProvider(LLMProvider):
    """Generic OpenAI-compatible endpoint (vLLM, Ollama, LM Studio, etc.)."""
    provider_name = "openai_compat"
    # Uses: OPENAI_COMPAT_API_KEY (optional), OPENAI_COMPAT_BASE_URL
    # For self-hosted models or any OpenAI-compatible server
```

#### Adding a New Provider

To add a new provider (e.g., Google Vertex, AWS Bedrock):

1. Create `llm_gateway/providers/my_provider.py`
2. Implement the `LLMProvider` protocol
3. Register in `llm_gateway/providers/registry.py`
4. Add the provider's env vars to `.env.example`
5. No changes needed to the gateway core, API, or any calling service

```python
# llm_gateway/providers/my_provider.py
class MyProvider:
    provider_name = "my_provider"

    def __init__(self, api_key: str, base_url: str):
        self.client = MySDK(api_key=api_key, base_url=base_url)

    async def complete(self, model, messages, **kwargs) -> ProviderResponse:
        raw = await self.client.chat(model=model, messages=messages, **kwargs)
        return ProviderResponse(
            content=raw.text,
            model=model,
            provider=self.provider_name,
            input_tokens=raw.usage.prompt_tokens,
            output_tokens=raw.usage.completion_tokens,
            total_tokens=raw.usage.total_tokens,
            raw_response=raw.to_dict(),
        )
    # ... implement embed(), list_models(), health_check()
```

The adapter is auto-discovered from the `providers/` directory at startup.

#### Provider Registry & Model Routing

The gateway maintains a **provider registry** and a **model routing table** configured via environment or YAML:

```yaml
# config/llm_providers.yaml (or equivalent env vars)
providers:
  anthropic:
    enabled: true
    api_key: "${ANTHROPIC_API_KEY}"
    default_for:
      - "claude-*"        # all Claude model strings

  openrouter:
    enabled: true
    api_key: "${OPENROUTER_API_KEY}"
    default_for:
      - "openrouter/*"    # explicit openrouter prefix
      - "google/*"        # route Google models through OpenRouter
      - "meta-llama/*"    # route Meta models through OpenRouter

  openai_compat:
    enabled: false        # disabled by default
    api_key: "${OPENAI_COMPAT_API_KEY}"
    base_url: "${OPENAI_COMPAT_BASE_URL}"
    default_for:
      - "local/*"         # self-hosted models

# Task-to-model routing (which model to use for each pipeline task)
task_routing:
  summarize_chunk: "claude-sonnet-4-20250514"
  summarize_document: "claude-sonnet-4-20250514"
  classify_ontology: "claude-haiku-4-5-20251001"
  extract_entities: "claude-haiku-4-5-20251001"
  embed: "voyage-3"         # embedding model
  query_embed: "voyage-3"   # embedding for search queries

# Fallback chain: if primary provider fails, try next
fallback_chain:
  - anthropic
  - openrouter
```

**Model resolution flow:**

1. Caller sends `model: "claude-sonnet-4-20250514"` (or omits model, using task routing)
2. Gateway checks task routing if `purpose` field maps to a specific model
3. Gateway matches model string against provider `default_for` patterns
4. `claude-*` matches → route to `anthropic` provider
5. If `anthropic` fails and fallback_chain is configured → try `openrouter` with the same model
6. Provider adapter normalizes request/response format

**Explicit provider override:** Callers can force a provider:

```json
{
  "model": "claude-sonnet-4-20250514",
  "provider": "openrouter",
  "messages": [...]
}
```

This sends the request through OpenRouter even though `claude-*` would normally match Anthropic.

#### Gateway Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/llm/complete` | Text completion / chat |
| POST | `/api/v1/llm/embed` | Generate embeddings |
| GET | `/api/v1/llm/usage` | Token usage statistics |
| GET | `/api/v1/llm/usage/by-service` | Usage broken down by caller |
| GET | `/api/v1/llm/usage/by-provider` | Usage broken down by provider |
| GET | `/api/v1/llm/models` | Available models across all providers |
| GET | `/api/v1/llm/providers` | List enabled providers and their status |
| GET | `/api/v1/llm/health` | Gateway health (checks all enabled providers) |
| PUT | `/api/v1/llm/routing` | Update task-to-model routing (admin only) |

#### Request/Response Schema

```json
// POST /api/v1/llm/complete
{
  "model": "claude-sonnet-4-20250514",      // optional if purpose maps to task_routing
  "provider": null,                          // optional: force a specific provider
  "messages": [...],
  "max_tokens": 4096,
  "temperature": 0.3,
  "system": "optional system prompt",
  "caller_service": "distiller",
  "caller_task_id": "uuid",
  "purpose": "summarize_chunk"               // used for task routing and token ledger
}

// Response (normalized across all providers)
{
  "id": "req-uuid",
  "content": "...",
  "model": "claude-sonnet-4-20250514",
  "provider": "anthropic",                   // which provider handled the request
  "usage": {
    "input_tokens": 1523,
    "output_tokens": 487,
    "total_tokens": 2010
  },
  "latency_ms": 1834
}
```

#### Token Ledger Data Model

```
LLMRequest:
  id: UUID
  caller_service: str
  caller_task_id: UUID (nullable)
  purpose: str
  model: str
  provider: str                    # which provider adapter handled this
  request_type: enum(completion, embedding)
  input_tokens: int
  output_tokens: int
  total_tokens: int
  estimated_cost_usd: decimal      # computed from provider pricing tables
  latency_ms: int
  status: enum(success, error, timeout, rate_limited, fallback)
  fallback_from: str (nullable)    # if this was a fallback, which provider failed
  error_message: str (nullable)
  created_at: datetime

LLMUsageSummary: (materialized view, refreshed hourly)
  date: date
  caller_service: str
  provider: str
  model: str
  request_count: int
  total_input_tokens: bigint
  total_output_tokens: bigint
  total_tokens: bigint
  estimated_cost_usd: decimal
  avg_latency_ms: float
  error_count: int
  fallback_count: int
```

#### Rate Limiting & Quota

- Per-service rate limits configurable via environment
- **Per-provider** rate limits to respect each provider's quotas independently
- Global rate limit as a safety ceiling
- Queue overflow: requests beyond rate limit are queued (up to 60s), then rejected
- Configurable per-model routing via task_routing config
- Provider-specific rate limit headers are parsed and respected (e.g., OpenRouter's `X-RateLimit-Remaining`)

#### Cost Tracking

The gateway maintains a pricing table per provider/model combination:

```python
PRICING = {
    ("anthropic", "claude-sonnet-4-20250514"): {"input": 3.00, "output": 15.00},  # per 1M tokens
    ("anthropic", "claude-haiku-4-5-20251001"): {"input": 0.80, "output": 4.00},
    ("openrouter", "anthropic/claude-sonnet-4"): {"input": 3.00, "output": 15.00},
    ("openrouter", "google/gemini-2.5-pro"): {"input": 1.25, "output": 10.00},
    # ... extensible via config
}
```

Estimated cost is logged per request and aggregated in the usage summary. The Admin UI displays cost breakdowns by provider, model, and task type.

#### Supported Providers (Initial)

| Provider | API Key Env Var | Use Case |
|----------|----------------|----------|
| Anthropic Direct | `ANTHROPIC_API_KEY` | Primary for Claude models — lowest latency, native features |
| OpenRouter | `OPENROUTER_API_KEY` | Multi-model access, fallback, cost optimization |
| OpenAI-Compatible | `OPENAI_COMPAT_API_KEY` | Self-hosted models (Ollama, vLLM, LM Studio) |

At least one provider must be enabled. The system validates this at startup and fails loudly if no provider is configured.

---

### 3.6 Layer 5 — Infrastructure & Scaling

**Purpose:** Containerization, orchestration, and persistent storage.

#### Container Architecture

| Container | Image | Purpose | Replicas |
|-----------|-------|---------|----------|
| `agentlake-api` | Python/FastAPI | API server (Layers 4A backend, 3, 1) | 1-N |
| `agentlake-ui` | Node/Nginx | React static files | 1-N |
| `agentlake-distiller` | Python/Celery | Processing workers (Layer 2) | 1-N |
| `agentlake-llm-gateway` | Python/FastAPI | LLM proxy (Layer 4B) | 1-2 |
| `agentlake-postgres` | PostgreSQL 16 + pgvector | Database | 1 (primary) |
| `agentlake-redis` | Redis 7 | Message broker + cache | 1 |
| `agentlake-minio` | MinIO | Object storage | 1 |

#### Persistent Volumes

All data must survive container restarts and be mountable across containers:

| Volume | Mount Point | Purpose | Backup Strategy |
|--------|------------|---------|-----------------|
| `pg-data` | `/var/lib/postgresql/data` | PostgreSQL data | pg_dump daily |
| `minio-data` | `/data` | Raw file storage | rsync / rclone |
| `redis-data` | `/data` | Redis persistence | RDB snapshots |

#### Docker Compose (Development)

- Single `docker-compose.yml` brings up all services
- `.env` file for configuration
- Hot-reload for API and UI services in dev mode
- Exposed ports: API (8000), UI (3000), MinIO console (9001), PgAdmin (5050)

#### Kubernetes (Production)

- Helm chart or Kustomize manifests
- Horizontal Pod Autoscaler on `agentlake-api` and `agentlake-distiller`
- PersistentVolumeClaims for all stateful services
- NetworkPolicy restricting LLM egress to `agentlake-llm-gateway` only
- Ingress with TLS termination
- ConfigMaps and Secrets for configuration

#### Backup & Recovery

- Automated daily PostgreSQL backups (pg_dump to mounted volume)
- MinIO bucket versioning enabled
- Redis RDB snapshots every 15 minutes
- Recovery runbook documented in `/docs/operations/backup-recovery.md`

---

## 4. Non-Functional Requirements

### 4.1 Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Search latency (keyword) | < 100ms p95 | 1M documents |
| Search latency (semantic) | < 200ms p95 | 1M documents |
| Search latency (hybrid) | < 250ms p95 | 1M documents |
| File upload throughput | 50 files/min | Mixed file types, avg 2MB |
| Processing pipeline latency | < 60s per file | Average document |
| API response time (non-search) | < 50ms p95 | Standard CRUD |
| UI initial load | < 2s | Cold start |
| Concurrent API connections | 500+ | Sustained load |

### 4.2 Reliability

- API uptime target: 99.9%
- Graceful degradation: if LLM gateway is down, uploads still accepted (processing queued)
- Idempotent file processing (same file re-uploaded → detected via SHA-256 hash)
- All database operations use transactions

### 4.3 Security

- API key authentication for external agents
- Session-based auth (JWT) for UI users
- RBAC: admin, editor, viewer roles
- All inter-service communication over internal network (no public exposure)
- LLM API keys stored in environment variables / K8s secrets only
- File upload: virus scanning hook (optional, pluggable)
- Input validation on all endpoints
- SQL injection protection via ORM (SQLAlchemy)
- CORS configuration for UI domain only

### 4.4 Observability

- Structured JSON logging (all services)
- Request tracing via correlation IDs
- Prometheus metrics endpoint on each service
- Recommended Grafana dashboards for: API latency, queue depth, LLM token usage, storage utilization

---

## 5. Technology Stack

| Component | Technology | Justification |
|-----------|-----------|---------------|
| API Framework | FastAPI (Python 3.12+) | Async, auto OpenAPI, type hints |
| ORM | SQLAlchemy 2.0 + Alembic | Mature, async support |
| Database | PostgreSQL 16 + pgvector | Vector search + relational in one |
| Task Queue | Celery 5 + Redis | Proven, horizontally scalable |
| Object Storage | MinIO | S3-compatible, self-hosted |
| Frontend | React 18 + TypeScript + Vite | Modern, fast dev cycle |
| UI Styling | TailwindCSS | Utility-first, rapid iteration |
| State Management | Zustand | Lightweight, no boilerplate |
| Data Fetching | Tanstack Query | Cache, retry, optimistic updates |
| Containerization | Docker + Docker Compose | Standard, portable |
| Orchestration | Kubernetes + Helm | Production scaling |

---

## 6. Testing Requirements

### 6.1 Unit Tests

- **Coverage target:** ≥ 85% line coverage
- **Framework:** pytest (backend), Vitest (frontend)
- All file adapters: test extraction for each supported type
- All API endpoints: test happy path + error cases
- All data models: test validation and serialization
- LLM gateway: test routing, token counting, error handling
- Search: test ranking, filtering, pagination

### 6.2 Integration Tests

- Full upload → process → search pipeline (end-to-end)
- API authentication and authorization flows
- Citation traceability: upload raw → verify citations in processed output resolve correctly
- Diff log generation on edits
- LLM gateway: verify no bypass (mock provider, assert all calls through gateway)

### 6.3 Functional Tests

- UI: Playwright end-to-end tests for critical flows
  - Upload a file and verify it appears in vault
  - Search and verify results
  - View document and click citation links
  - Edit document and verify diff log
- API: full scenario tests using httpx/pytest
  - Multi-file upload with tags → search → download → edit cycle

### 6.4 Scale Tests

- **Load test tool:** Locust
- **Scenarios:**
  - 100 concurrent search requests against 100K documents
  - 50 concurrent file uploads (mixed types)
  - 500 concurrent API read requests
  - Queue backpressure: 1000 files submitted, verify processing completes without loss
- **Performance regression:** CI runs a subset of scale tests on every merge

### 6.5 Testing Infrastructure

- Docker Compose test profile with pre-seeded data
- Pytest fixtures for database setup/teardown
- Factory Boy for model factories
- VCR.py / respx for LLM API call recording and playback

---

## 7. Documentation Requirements

| Document | Location | Description |
|----------|----------|-------------|
| API Reference | Auto-generated `/docs` | FastAPI Swagger UI |
| Deployment Guide | `/docs/deployment.md` | Docker Compose + K8s setup |
| Developer Guide | `/docs/development.md` | Local setup, architecture, contributing |
| Operations Guide | `/docs/operations/` | Backup, recovery, monitoring, scaling |
| File Adapter Guide | `/docs/extending-adapters.md` | How to add new file type support |
| Agent Integration Guide | `/docs/agent-integration.md` | How external agents discover and use the API |
| Data Ontology Reference | `/docs/ontology.md` | Common ontology schema and field definitions |

---

## 8. Project Structure

```
agentlake/
├── CLAUDE.md                    # Claude Code project instructions
├── docker-compose.yml           # Development compose
├── docker-compose.test.yml      # Test compose with seeded data
├── docker-compose.prod.yml      # Production-like compose
├── .env.example                 # Environment variable template
├── Makefile                     # Common commands
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/                 # Database migrations
│   │   └── versions/
│   ├── src/
│   │   └── agentlake/
│   │       ├── __init__.py
│   │       ├── main.py          # FastAPI app factory
│   │       ├── config.py        # Pydantic settings
│   │       ├── models/          # SQLAlchemy models
│   │       │   ├── file.py
│   │       │   ├── tag.py
│   │       │   ├── document.py
│   │       │   ├── diff_log.py
│   │       │   ├── llm_request.py
│   │       │   └── user.py
│   │       ├── schemas/         # Pydantic request/response schemas
│   │       │   ├── vault.py
│   │       │   ├── query.py
│   │       │   ├── llm.py
│   │       │   └── discover.py
│   │       ├── api/             # FastAPI routers
│   │       │   ├── vault.py     # Layer 1 endpoints
│   │       │   ├── query.py     # Layer 3 endpoints
│   │       │   ├── discover.py  # Agent discovery
│   │       │   ├── llm.py       # Layer 4B endpoints
│   │       │   └── admin.py     # Admin endpoints
│   │       ├── services/        # Business logic
│   │       │   ├── storage.py   # MinIO interactions
│   │       │   ├── search.py    # Search engine
│   │       │   ├── processing.py # Orchestrates Layer 2
│   │       │   ├── llm_client.py # Internal LLM gateway client
│   │       │   └── diff.py      # Diff generation
│   │       ├── adapters/        # File type adapters
│   │       │   ├── registry.py
│   │       │   ├── text.py
│   │       │   ├── markdown.py
│   │       │   ├── pdf.py
│   │       │   ├── docx.py
│   │       │   ├── xlsx.py
│   │       │   ├── pptx.py
│   │       │   ├── csv_adapter.py
│   │       │   ├── json_adapter.py
│   │       │   ├── image.py
│   │       │   └── code.py
│   │       ├── workers/         # Celery tasks
│   │       │   ├── celery_app.py
│   │       │   ├── process_file.py
│   │       │   └── generate_embeddings.py
│   │       ├── llm_gateway/     # Layer 4B service
│   │       │   ├── app.py
│   │       │   ├── proxy.py
│   │       │   ├── config.py
│   │       │   ├── token_ledger.py
│   │       │   ├── rate_limiter.py
│   │       │   └── providers/       # Modular provider adapters
│   │       │       ├── __init__.py
│   │       │       ├── base.py      # LLMProvider protocol + ProviderResponse
│   │       │       ├── registry.py  # Provider registry + model routing
│   │       │       ├── format.py    # Message format normalization
│   │       │       ├── anthropic.py # Direct Anthropic API
│   │       │       ├── openrouter.py# OpenRouter multi-model gateway
│   │       │       └── openai_compat.py # Generic OpenAI-compatible
│   │       └── core/            # Shared utilities
│   │           ├── database.py
│   │           ├── auth.py
│   │           ├── middleware.py
│   │           └── exceptions.py
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── unit/
│   │   │   ├── test_adapters/
│   │   │   ├── test_models/
│   │   │   ├── test_services/
│   │   │   └── test_llm_gateway/
│   │   ├── integration/
│   │   │   ├── test_upload_pipeline.py
│   │   │   ├── test_search.py
│   │   │   ├── test_citations.py
│   │   │   └── test_llm_routing.py
│   │   └── scale/
│   │       ├── locustfile.py
│   │       └── test_search_perf.py
│   └── Dockerfile
│
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/               # API client
│   │   │   ├── client.ts
│   │   │   ├── vault.ts
│   │   │   ├── query.ts
│   │   │   └── admin.ts
│   │   ├── components/        # Reusable components
│   │   │   ├── SearchBar.tsx
│   │   │   ├── FileUpload.tsx
│   │   │   ├── DocumentCard.tsx
│   │   │   ├── MarkdownRenderer.tsx
│   │   │   ├── TagPicker.tsx
│   │   │   ├── FilterSidebar.tsx
│   │   │   └── DiffViewer.tsx
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Search.tsx
│   │   │   ├── DocumentView.tsx
│   │   │   ├── Upload.tsx
│   │   │   ├── VaultBrowser.tsx
│   │   │   ├── TagsManager.tsx
│   │   │   └── Admin.tsx
│   │   ├── stores/            # Zustand stores
│   │   │   ├── authStore.ts
│   │   │   └── uiStore.ts
│   │   └── styles/
│   │       └── globals.css
│   ├── tests/
│   │   ├── components/
│   │   └── e2e/
│   │       └── playwright/
│   └── Dockerfile
│
├── k8s/                        # Kubernetes manifests
│   ├── base/
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── postgres.yaml
│   │   ├── redis.yaml
│   │   ├── minio.yaml
│   │   ├── api.yaml
│   │   ├── ui.yaml
│   │   ├── distiller.yaml
│   │   ├── llm-gateway.yaml
│   │   └── network-policy.yaml
│   └── overlays/
│       ├── dev/
│       └── prod/
│
├── docs/
│   ├── deployment.md
│   ├── development.md
│   ├── ontology.md
│   ├── agent-integration.md
│   ├── extending-adapters.md
│   └── operations/
│       ├── backup-recovery.md
│       ├── monitoring.md
│       └── scaling.md
│
└── scripts/
    ├── seed_data.py            # Seed test data
    ├── backup.sh               # Backup script
    └── migrate.sh              # Run migrations
```

---

## 9. Milestones

| Phase | Scope | Duration |
|-------|-------|----------|
| Phase 1 | Layer 5 infra + Layer 1 (upload, store, tag) + Layer 4B (gateway stub) | Week 1-2 |
| Phase 2 | Layer 2 processing pipeline (with incremental reprocessing) + Layer 4B full implementation | Week 3-4 |
| Phase 3 | Layer 3 search (keyword + semantic + hybrid) + Entity Graph (Apache AGE) | Week 5-6 |
| Phase 4 | Layer 4A API (with SSE streaming) + React UI + MCP Server | Week 7-9 |
| Phase 5 | Testing (unit, integration, functional, scale) | Week 10-11 |
| Phase 6 | Documentation + Claude Skills file + external integration guides + K8s manifests + polish | Week 12 |

---

## 10. Additional Feature Specifications

The following features are incorporated into the initial development and are specified in detail in separate documents. These are NOT future work — they are required in v1.0.

| Feature | Specification Document | Owning Agent(s) |
|---------|----------------------|-----------------|
| SSE Streaming | `specs/STREAMING.md` | Agent 4 (API), Agent 6 (Frontend) |
| Incremental Reprocessing | `specs/INCREMENTAL_REPROCESSING.md` | Agent 2 (Pipeline), Agent 3 (Search) |
| Entity Relationship Graph | `specs/ENTITY_GRAPH.md` | Agent 3 (Search), Agent 4 (API), Agent 6 (Frontend) |
| MCP Server | `specs/MCP_SERVER.md` | Agent 10 (new) |
| Claude Skills File | `specs/CLAUDE_SKILL.md` | Agent 10 (new) |
| External Integration Docs | `docs/external-integration/` | Agent 8 (Docs), Agent 10 |

---

## 11. Future Work (Post-v1.0)

- **Multi-tenancy:** Add tenant isolation and per-tenant quotas.
- **Plugin marketplace:** Allow third-party file adapters and processing plugins.
- **Federated search:** Query across multiple AgentLake instances.
- **Real-time collaborative editing:** Multi-user document editing with conflict resolution.


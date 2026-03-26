# AgentLake Development Agents

## Parallel Agent Architecture for Claude Code

This document defines the development agents that will build AgentLake in parallel. Each agent has a clear scope, input dependencies, and output deliverables. Agents are designed to minimize blocking dependencies and maximize parallel execution.

---

## Execution Order

```
Phase 1 (Foundation) — No dependencies, run in parallel:
  ├── Agent 0: Scaffold
  ├── Agent 7: Infrastructure
  └── Agent 8: Documentation (starts, continues throughout)

Phase 2 (Core Services) — Depends on Phase 1:
  ├── Agent 1: Storage (Layer 1)
  ├── Agent 5: LLM Gateway (Layer 4B)
  └── Agent 6: Frontend Shell (Layer 4A UI)

Phase 3 (Processing & Search) — Depends on Phase 2:
  ├── Agent 2: Processing Pipeline (Layer 2) — includes incremental reprocessing
  └── Agent 3: Search Engine (Layer 3) — includes Entity Graph (Apache AGE)

Phase 4 (API & Integration) — Depends on Phase 3:
  ├── Agent 4: API Layer (Layer 4A Backend) — includes SSE streaming + graph endpoints
  ├── Agent 6: Frontend Features (continued) — includes graph visualization
  └── Agent 10: MCP Server + External Integration

Phase 5 (Quality) — Depends on Phase 4:
  └── Agent 9: Testing & Scale
```

---

## Agent 0: Scaffold Agent

**Purpose:** Create the complete project skeleton, dependency files, and configuration.

**Scope:**
- Initialize the monorepo directory structure as defined in PRD section 8
- Create `pyproject.toml` with all Python dependencies
- Create `package.json` with all frontend dependencies
- Create `alembic.ini` and initial migration setup
- Create `.env.example` with all environment variables
- Create `Makefile` with common commands
- Set up `conftest.py` with pytest fixtures for database, MinIO, Redis
- Create base Pydantic settings module (`config.py`)
- Create database connection module (`core/database.py`)
- Create base SQLAlchemy models (abstract base, mixins)
- Create empty router stubs for all API modules
- Set up Celery app configuration
- Create Dockerfile stubs for backend and frontend

**Output Files:**
```
agentlake/
├── pyproject.toml
├── .env.example
├── Makefile
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/env.py
│   ├── src/agentlake/__init__.py
│   ├── src/agentlake/main.py
│   ├── src/agentlake/config.py
│   ├── src/agentlake/core/database.py
│   ├── src/agentlake/core/auth.py (stub)
│   ├── src/agentlake/core/middleware.py
│   ├── src/agentlake/core/exceptions.py
│   ├── src/agentlake/models/__init__.py
│   ├── src/agentlake/workers/celery_app.py
│   ├── tests/conftest.py
│   └── Dockerfile
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── index.html
│   ├── src/main.tsx
│   ├── src/App.tsx (shell)
│   └── Dockerfile
```

**Dependencies:** None
**Blocking:** All other agents depend on this completing first.

---

## Agent 1: Storage Agent (Layer 1 — Vault)

**Purpose:** Implement raw file storage, MinIO integration, tag system, and file adapters.

**Scope:**

### 1A: Data Models
- `models/file.py` — File SQLAlchemy model with all fields from PRD
- `models/tag.py` — Tag and FileTag models
- Alembic migration for Layer 1 tables

### 1B: MinIO Service
- `services/storage.py` — MinIO client wrapper
  - `upload_file(file_bytes, filename, content_type) -> storage_key`
  - `download_file(storage_key) -> bytes`
  - `delete_file(storage_key) -> bool`
  - `get_presigned_url(storage_key, expires) -> str`
- Bucket auto-creation on startup
- SHA-256 hash computation for deduplication

### 1C: File Adapters
- `adapters/registry.py` — Adapter registry with auto-discovery
- `adapters/base.py` — Protocol definition and ExtractedContent dataclass
- Individual adapters:
  - `text.py` — .txt, .md handling
  - `markdown.py` — .md with frontmatter parsing
  - `pdf.py` — PyMuPDF extraction with page tracking
  - `docx.py` — python-docx extraction with section tracking
  - `xlsx.py` — openpyxl extraction with sheet/cell tracking
  - `pptx.py` — python-pptx extraction with slide tracking
  - `csv_adapter.py` — CSV/TSV with header detection
  - `json_adapter.py` — JSON/YAML/XML with structure preservation
  - `image.py` — Image metadata extraction (dimensions, EXIF)
  - `code.py` — Source code with language detection

### 1D: Unit Tests
- Test each adapter with sample files (create test fixtures)
- Test MinIO service (mocked)
- Test tag CRUD operations
- Test file deduplication logic

**Dependencies:** Agent 0 (skeleton)
**Output:** Complete Layer 1 implementation with tests

---

## Agent 2: Processing Pipeline Agent (Layer 2 — Distiller)

**Purpose:** Implement the agentic processing pipeline from raw file to processed markdown.

**Scope:**

### 2A: Chunking Engine
- `services/chunker.py` — SemanticChunker implementation
  - Respect structural boundaries
  - Configurable max_tokens and overlap
  - Source locator preservation
- Unit tests for chunking edge cases

### 2B: LLM Client (Internal)
- `services/llm_client.py` — Client that calls Layer 4B gateway
  - `complete(messages, model, purpose) -> CompletionResponse`
  - `embed(texts) -> list[list[float]]`
  - Always includes caller_service and purpose headers
  - Retry logic with backoff
  - **Critical: this is the ONLY module that calls the LLM gateway**

### 2C: Processing Pipeline
- `workers/process_file.py` — Main Celery task
  - Stage 1: Call adapter registry to extract content
  - Stage 2: Chunk extracted content
  - Stage 3: Summarize each chunk via LLM (system prompts in `prompts/`)
  - Stage 4: Generate citations linking summaries to source chunks
  - Stage 5: Classify via ontology (LLM call for category, entities, temporal)
  - Stage 6: Assemble final markdown with frontmatter, store to Layer 3
- `workers/generate_embeddings.py` — Embedding generation task (called from Stage 6)
- Priority queue handling (high/default/low)
- Error handling with retry and DLQ

### 2D: Prompt Templates
- `prompts/summarize_chunk.py` — System prompt for chunk summarization
- `prompts/summarize_document.py` — System prompt for document-level rollup
- `prompts/classify_ontology.py` — System prompt for ontology classification
- `prompts/extract_entities.py` — System prompt for entity extraction
- All prompts instruct the LLM to output structured YAML/JSON

### 2E: Diff Log Service
- `services/diff.py` — Diff generation and storage
  - `create_initial_diff(document_id, source_file_id, after_text)`
  - `create_edit_diff(document_id, before_text, after_text, justification, created_by)`
  - Text diff computation (unified diff format stored)

### 2F: Unit + Integration Tests
- Test each pipeline stage independently (mocked LLM responses)
- Test full pipeline end-to-end with recorded LLM responses (VCR)
- Test retry and error handling
- Test diff generation

### 2G: Incremental Reprocessing (CRITICAL — see `specs/INCREMENTAL_REPROCESSING.md`)
- `services/chunker.py` — add `content_hash` computation per chunk (SHA-256)
- `workers/process_file.py` — implement `compute_chunk_delta()` algorithm
  - Hash-based exact match detection for unchanged chunks
  - Jaccard similarity for modified vs. new chunk classification
  - Configurable similarity threshold (`INCREMENTAL_SIMILARITY_THRESHOLD`)
- Modified chunks: re-summarize + re-embed only those chunks via LLM
- Unchanged chunks: reuse existing summaries and embeddings (zero LLM calls)
- New chunks: full summarization pipeline
- Removed chunks: mark removed, clean from search index
- Re-classify ontology only if >20% of chunks changed
- DiffLog metadata: record chunk delta counts (unchanged, modified, added, removed)
- `reprocess_file_task`: supports `mode=incremental` (default) and `mode=full`
- Unit tests: chunk delta computation, similarity boundary, hash matching
- Integration tests: upload → process → re-upload with edit → verify only changed chunks re-summarized

### 2H: Relationship Extraction for Entity Graph
- `prompts/extract_relationships.py` — LLM prompt for relationship extraction between entities
- Stage 5b in pipeline: after entity extraction, extract relationships
- Output: list of `{source, target, relationship_type, description, confidence}`
- Pass extracted relationships to Agent 3's graph population service
- Unit tests with mocked LLM responses for relationship extraction

**Dependencies:** Agent 0, Agent 1 (adapters), Agent 5 (LLM gateway API contract)
**Output:** Complete Layer 2 implementation with incremental reprocessing and relationship extraction

---

## Agent 3: Search Engine Agent (Layer 3 — QueryStore)

**Purpose:** Implement the processed data store with full-text, semantic, and hybrid search.

**Scope:**

### 3A: Data Models
- `models/document.py` — ProcessedDocument, DocumentChunk, Citation models
- `models/diff_log.py` — DiffLog model
- Alembic migration for Layer 3 tables (including pgvector indexes)

### 3B: Search Service
- `services/search.py` — Core search engine
  - `keyword_search(query, filters, limit, offset) -> SearchResults`
  - `semantic_search(query_embedding, filters, limit, offset) -> SearchResults`
  - `hybrid_search(query, filters, weights, limit, offset) -> SearchResults`
  - Reciprocal Rank Fusion implementation
  - Filter builder (tags, category, entities, date range, file type)
  - Search result highlighting (snippet extraction around matches)

### 3C: Document Service
- `services/documents.py` — CRUD for processed documents
  - `create_document(...)` — Insert with embedding
  - `update_document(id, body, justification, editor)` — Version + diff log
  - `get_document(id)` — With citations
  - `get_document_history(id)` — All versions with diffs
  - `list_documents(filters, pagination)` — Browse with filtering

### 3D: Indexing
- PostgreSQL index configuration in migrations
- HNSW index tuning parameters
- Materialized view for category/entity aggregations
- Index rebuild/refresh management

### 3E: Entity Relationship Graph (CRITICAL — see `specs/ENTITY_GRAPH.md`)
- Install and configure Apache AGE PostgreSQL extension
- Alembic migration: create graph schema (`SELECT create_graph('agentlake_graph')`)
- `services/graph.py` — Graph service
  - `upsert_entity(name, type, document_id)` — deduplicate by canonical_name
  - `add_relationship(source, target, type, description, confidence, document_id)`
  - `get_entity_neighbors(entity_id, depth, relationship_types)`
  - `shortest_path(from_id, to_id)`
  - `search_entities(query, type_filter)`
  - `get_entity_documents(entity_id)`
  - `get_graph_stats()`
- `services/graph.py` — Entity canonicalization (lowercase, strip suffixes)
- Relationship weight: incremented when same relationship found in multiple documents
- Graph rebuild capability: reconstruct from ProcessedDocument.entities if needed
- Unit tests: canonicalization, dedup, traversal, shortest path
- Integration tests: upload related docs → verify graph populated → query neighbors
- Performance: 100K entities, 500K edges → traversal under 200ms

### 3F: Unit + Performance Tests
- Test keyword search with known corpus
- Test semantic search with known embeddings
- Test hybrid search score fusion
- Test filtering combinations
- Test pagination (cursor-based)
- Test entity graph traversal at depth 1, 2, 3
- Test entity deduplication across multiple documents
- Performance benchmarks: search latency at 1K, 10K, 100K documents
- Performance benchmarks: graph traversal at 10K, 100K entities

**Dependencies:** Agent 0, Agent 5 (for embedding generation via LLM gateway)
**Output:** Complete Layer 3 implementation with Entity Graph, tests, and benchmarks

---

## Agent 4: API Agent (Layer 4A — Backend)

**Purpose:** Implement all FastAPI endpoints, authentication, and API documentation.

**Scope:**

### 4A: Authentication & Authorization
- `core/auth.py` — Full implementation
  - API key validation (hashed comparison)
  - JWT session management for UI
  - Role-based access control (admin, editor, viewer, agent)
  - Dependency injection for FastAPI
- `models/user.py` — API key model

### 4B: Vault Endpoints
- `api/vault.py` — Complete Layer 1 REST API
  - File upload with multipart handling
  - File listing with pagination and tag filtering
  - File metadata, download, delete
  - Tag CRUD and file-tag management
  - Reprocessing trigger

### 4C: Query Endpoints
- `api/query.py` — Complete Layer 3 REST API
  - Hybrid search endpoint
  - Document CRUD with edit workflow (diff log integration)
  - Citation retrieval
  - Category/entity listing

### 4D: Discovery Endpoints
- `api/discover.py` — Agent discovery API
  - System description endpoint
  - Schema definition endpoint
  - Tags, categories, stats endpoints

### 4E: Admin Endpoints
- `api/admin.py` — Administration API
  - API key management
  - Token usage statistics (proxied from Layer 4B)
  - Processing queue status
  - System health

### 4F: Middleware & Error Handling
- `core/middleware.py` — Request ID injection, logging, timing
- `core/exceptions.py` — Custom exception classes + handlers
- CORS configuration
- Rate limiting per API key

### 4G: SSE Streaming Endpoints (see `specs/STREAMING.md`)
- `api/streaming.py` — SSE endpoints
  - `GET /api/v1/stream/processing/{file_id}` — processing stage updates
  - `GET /api/v1/stream/search` — streaming search results
- Redis Pub/Sub integration: subscribe to `processing:{file_id}` channels
- `WS /ws/dashboard` — WebSocket endpoint for live dashboard stats
- SSE event format: `event: stage_update\ndata: {...}\n\n`
- Reconnection support via `Last-Event-ID` header
- Tests: SSE connection, event delivery, reconnection, timeout behavior

### 4H: Graph API Endpoints (see `specs/ENTITY_GRAPH.md`)
- `api/graph.py` — Entity graph REST API
  - `GET /api/v1/graph/search` — search entities by name/type
  - `GET /api/v1/graph/entity/{id}` — entity with relationships
  - `GET /api/v1/graph/entity/{id}/neighbors` — traversal with depth + filters
  - `GET /api/v1/graph/path` — shortest path between two entities
  - `GET /api/v1/graph/entity/{id}/documents` — documents mentioning entity
  - `GET /api/v1/graph/relationships` — list by type
  - `GET /api/v1/graph/stats` — node/edge counts
- Register router in `main.py`
- Tests: every graph endpoint, traversal depth limits, empty graph edge cases

### 4I: Tests
- Test every endpoint (happy path + error cases)
- Test authentication/authorization matrix
- Test rate limiting
- Test pagination edge cases
- Test error response format (RFC 7807)
- Test SSE streaming delivery and format
- Test graph endpoints with seeded graph data

**Dependencies:** Agent 1, Agent 2, Agent 3, Agent 5
**Output:** Complete API layer with streaming, graph endpoints, OpenAPI documentation, and tests

---

## Agent 5: LLM Gateway Agent (Layer 4B)

**Purpose:** Implement the centralized, provider-agnostic LLM proxy with modular provider adapters and token ledger.

**Scope:**

### 5A: Provider Adapter Interface
- `llm_gateway/providers/base.py` — Protocol definition: `LLMProvider`, `ProviderResponse`, `ModelInfo`, `ProviderHealth`
- `llm_gateway/providers/format.py` — Message format normalization (Anthropic ↔ OpenAI style)

### 5B: Built-In Provider Adapters
- `llm_gateway/providers/anthropic.py` — Direct Anthropic Claude API adapter
  - Native message format (no conversion needed)
  - Handles Anthropic-specific features (content blocks, tool use)
  - Delegates embeddings to configured embedding provider
- `llm_gateway/providers/openrouter.py` — OpenRouter multi-model adapter
  - OpenAI-compatible chat format with message conversion
  - OpenRouter-specific headers (HTTP-Referer, X-Title)
  - Parses OpenRouter rate-limit and cost headers
  - Supports all OpenRouter models (Anthropic, Google, Meta, etc.)
- `llm_gateway/providers/openai_compat.py` — Generic OpenAI-compatible adapter
  - Configurable base_url for any OpenAI-compatible server
  - Works with vLLM, Ollama, LM Studio, etc.
  - Optional API key (some local servers don't require auth)
- Unit tests for each adapter with mocked HTTP responses

### 5C: Provider Registry & Model Routing
- `llm_gateway/providers/registry.py` — Provider registry
  - Auto-discovery and registration of enabled providers
  - Model-to-provider routing via glob patterns (e.g., `claude-*` → anthropic)
  - Task-to-model routing (purpose → model mapping)
  - Fallback chain: if primary provider fails, try next in chain
  - Pricing table for cost estimation per (provider, model) pair
  - `resolve_provider(model, provider, purpose)` method
- `llm_gateway/config.py` — Gateway configuration
  - Pydantic settings with all provider API keys
  - YAML config loading for advanced routing rules
  - Validation: at least one provider must be enabled at startup
- Unit tests for routing logic, fallback chains, pattern matching

### 5D: Gateway Service
- `llm_gateway/app.py` — Standalone FastAPI app for the gateway
  - Startup: initialize provider registry, validate config
  - Endpoints: complete, embed, usage, models, providers, health, routing
- `llm_gateway/proxy.py` — Request handling
  - Resolve provider via registry
  - Execute request with timeout
  - On failure: attempt fallback if configured
  - Normalize all responses to `ProviderResponse` shape
  - Log to token ledger asynchronously

### 5E: Token Ledger
- `llm_gateway/token_ledger.py` — Usage tracking
  - Async logging (non-blocking to request path)
  - `LLMRequest` model with `provider`, `fallback_from`, `estimated_cost_usd` fields
  - `LLMUsageSummary` materialized view (grouped by provider + model)
  - Usage query methods: by service, by provider, by model, by time range
  - Cost aggregation queries

### 5F: Rate Limiter
- `llm_gateway/rate_limiter.py` — Multi-level rate limiting
  - Per-service rate limiting (token bucket via Redis)
  - **Per-provider** rate limiting (respect each provider's quotas independently)
  - Global rate limit as safety ceiling
  - Queue overflow handling (60s queue, then reject)
  - Parse and respect provider rate-limit response headers

### 5G: Authentication
- Internal service token validation
- Only accept requests from known internal services

### 5H: Alembic Migration
- Migration for `llm_requests` table (with provider, cost, fallback columns)
- Migration for `llm_usage_summary` materialized view
- Migration for `api_keys` table

### 5I: Tests
- Test each provider adapter (mocked HTTP)
- Test provider registry: model routing, fallback chain, pattern matching
- Test message format conversion (Anthropic ↔ OpenAI)
- Test gateway end-to-end: request → resolve → call → log → respond
- Test rate limiting behavior (per-service AND per-provider)
- Test fallback: primary fails → secondary succeeds → ledger records `fallback` status
- Test cost estimation accuracy
- Test startup validation (no providers enabled → fail loudly)
- Test that unauthorized callers are rejected

**Dependencies:** Agent 0
**Output:** Complete modular LLM gateway service with provider adapters and tests

---

## Agent 6: Frontend Agent (Layer 4A — UI)

**Purpose:** Build the React/TypeScript UI.

**Scope:**

### 6A: Foundation (Phase 2)
- Design system: color tokens, typography, spacing
- Layout shell: sidebar navigation, header, main content area
- Router setup with Tanstack Router
- API client setup with Tanstack Query
- Auth context and login flow
- Dark/light mode toggle
- WebSocket connection for real-time updates

### 6B: Core Pages (Phase 4)
- **Dashboard** — Stats cards with live WebSocket updates, recent activity, quick search
- **Search** — Full search interface with filters, SSE streaming results (results animate in)
- **Document Viewer** — Markdown rendering, citation panel, edit mode, history
- **Upload** — Drag-drop upload, tag assignment, SSE processing progress (live stage updates)
- **Vault Browser** — File grid/list view, tag filtering, preview
- **Tags Manager** — Tag CRUD with usage stats
- **Admin** — Token usage dashboard (by provider/model), queue status, API key management
- **Graph Explorer** (`/graph`) — Interactive entity relationship visualization (NEW)

### 6C: Components
- `SearchBar` — Type-ahead with debounce
- `FileUpload` — Drag-drop with progress
- `DocumentCard` — Search result card with snippet
- `MarkdownRenderer` — With syntax highlighting and citation links
- `TagPicker` — Autocomplete multi-select
- `FilterSidebar` — Collapsible filter groups
- `DiffViewer` — Side-by-side or inline diff display
- `TokenUsageChart` — Recharts-based usage visualization (with provider breakdown)
- `ProcessingProgress` — SSE-powered live processing stage indicator (NEW)
- `GraphVisualization` — D3 force-directed graph of entity relationships (NEW)
- `EntityCard` — Entity detail card with type icon and document count (NEW)

### 6D: Graph Explorer Page (see `specs/ENTITY_GRAPH.md`)
- Interactive force-directed graph using D3.js or react-force-graph
- Click entity node → expand neighbors (lazy load via API)
- Edge thickness = relationship weight (more documents → thicker)
- Color-coded by entity type: org=blue, person=green, product=teal, technology=amber
- Filter sidebar: entity type, relationship type, minimum weight
- Click relationship edge → shows source document and citation
- Search bar within graph page to find and center on an entity
- Keyboard shortcut: Cmd+G to navigate to graph view

### 6E: SSE/WebSocket Integration (see `specs/STREAMING.md`)
- `hooks/useProcessingStream.ts` — SSE hook for processing status updates
- `hooks/useSearchStream.ts` — SSE hook for streaming search results
- `hooks/useDashboardFeed.ts` — WebSocket hook for live dashboard counters
- Upload page: after upload, progress card shows real-time stage updates with progress bar
- Search page: results appear incrementally with fade-in animation
- Dashboard: stat cards update live with subtle pulse on change

### 6F: Design Requirements
- Dark mode default: deep charcoal background, high-contrast text
- Accent color: electric teal (#14b8a6)
- Monospace font for code/data: JetBrains Mono
- Display font: something distinctive (Satoshi, Cabinet Grotesk, or similar)
- Subtle grid pattern background texture
- Keyboard shortcuts: Cmd+K for search, Cmd+U for upload, Cmd+G for graph

### 6G: Tests
- Component unit tests with Vitest + Testing Library
- Playwright E2E tests for critical flows:
  - Upload → process (watch SSE progress) → search → view → edit cycle
  - Citation link navigation
  - Tag management
  - Graph explorer: search entity → expand neighbors → click edge → view source doc
  - Streaming search: verify results appear incrementally

**Dependencies:** Agent 0 (skeleton), Agent 4 (API contract + SSE/WS endpoints + graph endpoints)
**Output:** Complete React UI with graph visualization, streaming, and tests

---

## Agent 7: Infrastructure Agent (Layer 5)

**Purpose:** Docker configuration, Kubernetes manifests, and operational tooling.

**Scope:**

### 7A: Docker
- `backend/Dockerfile` — Multi-stage build (builder + runtime)
- `frontend/Dockerfile` — Build + Nginx serve
- `docker-compose.yml` — Development environment
  - All 7 containers with proper networking
  - Volume mounts for hot-reload
  - Health checks
  - Proper startup ordering (depends_on with healthcheck)
- `docker-compose.test.yml` — Test environment with seeded data
- `docker-compose.prod.yml` — Production-like (no hot-reload, resource limits)

### 7B: Kubernetes
- `k8s/base/` — Kustomize base manifests for all services
- `k8s/base/namespace.yaml`
- `k8s/base/postgres.yaml` — StatefulSet with PVC
- `k8s/base/redis.yaml` — StatefulSet with PVC
- `k8s/base/minio.yaml` — StatefulSet with PVC
- `k8s/base/api.yaml` — Deployment + HPA + Service
- `k8s/base/ui.yaml` — Deployment + Service
- `k8s/base/distiller.yaml` — Deployment + HPA (queue-based scaling)
- `k8s/base/llm-gateway.yaml` — Deployment + Service
- `k8s/base/network-policy.yaml` — Restrict LLM egress
- `k8s/base/ingress.yaml` — Ingress with TLS
- `k8s/overlays/dev/` — Dev overrides (single replica, lower resources)
- `k8s/overlays/prod/` — Prod overrides (HPA ranges, resource requests)

### 7C: Scripts
- `scripts/backup.sh` — PostgreSQL + MinIO backup
- `scripts/migrate.sh` — Run Alembic migrations
- `scripts/seed_data.py` — Seed test data for development
- `Makefile` targets for common operations

### 7D: Tests
- Docker Compose: `make test-compose` brings up all services, runs health checks
- K8s: validate manifests with `kubectl --dry-run`

**Dependencies:** Agent 0
**Output:** Complete infrastructure configuration

---

## Agent 8: Documentation Agent

**Purpose:** Write all project documentation including external integration guides.

**Scope:**
- `docs/deployment.md` — Complete deployment guide (Docker + K8s)
- `docs/development.md` — Local development setup guide
- `docs/ontology.md` — Common data ontology reference
- `docs/agent-integration.md` — Guide for external AI agents to use the REST API
- `docs/extending-adapters.md` — How to add new file type support
- `docs/operations/backup-recovery.md` — Backup and restore procedures
- `docs/operations/monitoring.md` — Metrics, dashboards, alerting
- `docs/operations/scaling.md` — Horizontal scaling guide
- `docs/external-integration/API_REFERENCE.md` — Complete endpoint reference for all consumers
- `docs/external-integration/MCP_CONNECTION_GUIDE.md` — How to connect via MCP from Claude Desktop, Claude Code, and custom clients
- `docs/external-integration/INTEGRATION_EXAMPLES.md` — Code examples in Python, TypeScript, shell, LangChain, n8n
- `README.md` — Project overview with quickstart

**Dependencies:** All other agents (documentation is written based on implementation)
**Output:** Complete documentation suite including external integration guides

---

## Agent 9: Testing & Scale Agent

**Purpose:** Integration tests, end-to-end tests, and scale/performance tests.

**Scope:**

### 9A: Integration Tests
- `tests/integration/test_upload_pipeline.py` — Full upload → process → query
- `tests/integration/test_search.py` — Search accuracy with known corpus
- `tests/integration/test_citations.py` — Citation traceability verification
- `tests/integration/test_llm_routing.py` — Verify all LLM calls go through gateway
- `tests/integration/test_edit_workflow.py` — Edit → diff log → version
- `tests/integration/test_incremental_reprocess.py` — Upload → process → re-upload with edit → verify only changed chunks re-summarized, verify LLM call count
- `tests/integration/test_entity_graph.py` — Upload related docs → verify graph populated → query neighbors → shortest path
- `tests/integration/test_streaming.py` — SSE processing stream delivers correct events in order; SSE search stream delivers results incrementally
- `tests/integration/test_mcp.py` — MCP server round-trip: connect → call each tool → verify results

### 9B: End-to-End Tests
- Playwright tests exercising the full system through the UI:
  - Upload → watch SSE progress → search → view → edit → verify diff
  - Graph explorer: search entity → expand → click edge → view doc
  - Streaming search: verify results appear one by one
- API-level scenario tests (multi-step workflows)

### 9C: Scale Tests
- `tests/scale/locustfile.py` — Locust load test definitions
  - Search endpoint under load (100, 500, 1000 concurrent)
  - Upload endpoint under load
  - Graph traversal under load
  - Mixed workload simulation
- `tests/scale/test_search_perf.py` — Search latency benchmarks at scale
  - Seed 10K, 50K, 100K documents
  - Measure p50, p95, p99 latencies
  - Validate against PRD targets
- `tests/scale/test_graph_perf.py` — Graph traversal benchmarks
  - Seed 10K, 100K entities with 5x edges
  - Measure traversal latency at depth 1, 2, 3

### 9D: Test Data
- `scripts/seed_data.py` — Generate realistic test data
  - Sample files of each supported type
  - Pre-generated processed documents with citations
  - Pre-generated entity graph with relationships
  - Tag hierarchy matching real usage patterns

**Dependencies:** All implementation agents
**Output:** Complete test suite with CI integration

---

## Agent 10: MCP Server & External Integration Agent

**Purpose:** Implement the MCP server, Claude Code skill file, and all external integration documentation.

**Scope:**

### 10A: MCP Server (see `specs/MCP_SERVER.md`)
- `backend/src/agentlake/mcp/__init__.py`
- `backend/src/agentlake/mcp/server.py` — MCP server entry point
  - stdio transport (for Claude Code / local use)
  - SSE transport (for remote / always-running)
  - Startup: connect to AgentLake REST API, validate API key
- `backend/src/agentlake/mcp/tools.py` — MCP tool implementations
  - `agentlake_discover` — wraps `GET /api/v1/discover`
  - `agentlake_search` — wraps `GET /api/v1/query/search`
  - `agentlake_get_document` — wraps `GET /api/v1/query/documents/{id}`
  - `agentlake_get_citations` — wraps `GET /api/v1/query/documents/{id}/citations`
  - `agentlake_upload` — wraps `POST /api/v1/vault/upload` (reads file from local path)
  - `agentlake_list_tags` — wraps `GET /api/v1/vault/tags`
  - `agentlake_graph_explore` — wraps `GET /api/v1/graph/search` + `GET /api/v1/graph/entity/{id}/neighbors`
  - `agentlake_edit_document` — wraps `PUT /api/v1/query/documents/{id}`
  - Each tool: translate MCP input → REST API call → format MCP output
- `backend/src/agentlake/mcp/resources.py` — MCP resource definitions
  - `agentlake://documents` — paginated document list
  - `agentlake://documents/{id}` — full document markdown
  - `agentlake://vault/{file_id}` — raw file metadata + download URI
- `backend/src/agentlake/mcp/prompts.py` — Pre-built MCP prompts
  - `research_topic` — multi-step research workflow
  - `entity_briefing` — entity-focused briefing workflow

### 10B: Claude Code Skill File (see `specs/CLAUDE_SKILL.md`)
- `skills/agentlake/SKILL.md` — Skill definition for Claude Code
  - Trigger patterns (search, upload, find, explore)
  - Configuration instructions (env vars or MCP)
  - Available operations with curl examples
  - Workflow patterns (research, meeting prep, upload-and-track)
  - Error handling guide

### 10C: Docker Integration
- Add `mcp-server` service to `docker-compose.yml`
- Add MCP server K8s manifest to `k8s/base/mcp-server.yaml`
- Environment variable: `MCP_SERVER_API_KEY` for the MCP server's API key

### 10D: Tests
- Unit: each MCP tool correctly translates input → REST call → output
- Integration: full MCP round-trip (connect → initialize → call tools → get results)
- Integration: verify MCP tool auth passes through to API
- Compatibility: test with Claude Desktop config format
- Compatibility: test stdio transport (spawn process, send MCP messages)

**Dependencies:** Agent 4 (REST API must be complete), Agent 3 (graph endpoints)
**Output:** Complete MCP server, skill file, and external integration suite

---

## Agent Communication Contract

Agents communicate through shared interfaces defined in these locations:

| Interface | File | Owner | Consumers |
|-----------|------|-------|-----------|
| File model | `models/file.py` | Agent 1 | Agent 2, 4 |
| ExtractedContent | `adapters/base.py` | Agent 1 | Agent 2 |
| ProcessedDocument model | `models/document.py` | Agent 3 | Agent 2, 4, 10 |
| LLM client interface | `services/llm_client.py` | Agent 2 | Agent 2, 3 |
| LLM Provider protocol | `llm_gateway/providers/base.py` | Agent 5 | Agent 5 (adapters) |
| Provider registry | `llm_gateway/providers/registry.py` | Agent 5 | Agent 5 (gateway core) |
| LLM gateway API | `llm_gateway/app.py` | Agent 5 | Agent 2 (via client) |
| Search interface | `services/search.py` | Agent 3 | Agent 4, 10 |
| Graph interface | `services/graph.py` | Agent 3 | Agent 4, 10 |
| Chunk delta | `workers/process_file.py` | Agent 2 | Agent 2 (internal) |
| SSE channels | Redis Pub/Sub | Agent 2, 4 | Agent 4 (SSE endpoints), Agent 6 (UI) |
| API schemas | `schemas/*.py` | Agent 4 | Agent 6, 10 |
| MCP tools | `mcp/tools.py` | Agent 10 | External MCP clients |
| Docker networking | `docker-compose.yml` | Agent 7 | All |

When an agent modifies a shared interface, it must update the corresponding tests and notify dependent agents by updating the `CHANGELOG.md`.

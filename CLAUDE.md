# CLAUDE.md — AgentLake Project Instructions

## Project Overview

AgentLake is a distributed, containerized, agent-friendly data lake. It ingests raw unstructured files, processes them through an LLM-powered pipeline into searchable markdown with citation traceability, and serves results through a REST API and React UI.

Read `PRD.md` for full requirements. Read `ARCHITECTURE.md` for technical design. Read `AGENTS.md` for agent scope definitions.

## Critical Invariants

These rules are NEVER violated:

1. **ALL LLM calls route through Layer 4B (LLM Gateway).** No service may import or call an LLM provider SDK directly. The only module that communicates with the LLM gateway is `services/llm_client.py`. Every other service calls `llm_client` methods.

2. **Every processed document has citations linking back to raw source data.** Citations use the format `[N](/api/v1/vault/files/{file_id}/download#chunk={chunk_index})`. No processed content exists without provenance.

3. **Every edit (human or automated) produces a DiffLog entry.** The diff log records before_text, after_text, justification, and who made the change. There are no silent mutations.

4. **All processed data uses the Common Data Ontology.** Every processed markdown document has YAML frontmatter conforming to the ontology schema defined in `docs/ontology.md` and the `ProcessedDocument` model.

5. **LLM API keys exist ONLY in the LLM Gateway service environment.** No other service, config file, or container has access to any provider API keys (Anthropic, OpenRouter, or any other). Adding a new provider means writing one adapter class in `llm_gateway/providers/` — zero changes to the gateway core or calling services.

6. **Reprocessing is incremental by default.** When a file is re-uploaded or reprocessed, only chunks whose content hash changed are re-summarized and re-embedded. Unchanged chunks reuse existing summaries. See `specs/INCREMENTAL_REPROCESSING.md`.

7. **Entity relationships are graph-native.** Entities and their relationships are stored in Apache AGE (PostgreSQL graph extension), not just JSONB. The graph is a derived index that can be rebuilt from document entities. See `specs/ENTITY_GRAPH.md`.

8. **All external integration goes through the REST API.** The MCP server, skill files, and all external clients call the REST API. No external client bypasses the API to access the database or services directly.

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Alembic, Celery 5, Redis
- **Database:** PostgreSQL 16 with pgvector extension + Apache AGE (graph)
- **Object Storage:** MinIO (S3-compatible)
- **Frontend:** React 18, TypeScript, Vite, TailwindCSS, Tanstack Query, Tanstack Router, Zustand, D3.js (graph)
- **Streaming:** SSE (processing status, search results), WebSocket (dashboard live feed)
- **MCP:** Model Context Protocol server for Claude Desktop / Claude Code integration
- **Testing:** pytest, Vitest, Playwright, Locust, Factory Boy
- **Containers:** Docker, Docker Compose, Kubernetes (Kustomize)

## Feature Specifications

New features have detailed specs in `specs/`:

| Spec | File | Description |
|------|------|-------------|
| Streaming | `specs/STREAMING.md` | SSE for processing status + search results, WebSocket for dashboard |
| Incremental Reprocessing | `specs/INCREMENTAL_REPROCESSING.md` | Only re-process changed chunks on re-upload |
| Entity Graph | `specs/ENTITY_GRAPH.md` | Apache AGE graph for entity relationships |
| MCP Server | `specs/MCP_SERVER.md` | Expose AgentLake as an MCP server |
| Claude Skill | `specs/CLAUDE_SKILL.md` | Skill file for Claude Code integration |

## Project Structure

```
agentlake/
├── CLAUDE.md              ← You are here
├── PRD.md                 ← Full product requirements
├── ARCHITECTURE.md        ← Technical architecture
├── AGENTS.md              ← Agent scope definitions
├── docker-compose.yml
├── .env.example
├── Makefile
├── specs/                 ← Feature specifications (new features)
│   ├── STREAMING.md
│   ├── INCREMENTAL_REPROCESSING.md
│   ├── ENTITY_GRAPH.md
│   ├── MCP_SERVER.md
│   └── CLAUDE_SKILL.md
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   ├── src/agentlake/     ← All backend source
│   │   ├── mcp/           ← MCP server (Agent 10)
│   │   └── ...
│   ├── tests/             ← All backend tests
│   └── Dockerfile
├── frontend/
│   ├── package.json
│   ├── src/               ← All frontend source
│   ├── tests/
│   └── Dockerfile
├── skills/                ← Claude Code skill files
│   └── agentlake/SKILL.md
├── k8s/                   ← Kubernetes manifests
├── docs/                  ← Documentation
│   ├── external-integration/  ← API reference, MCP guide, integration examples
│   └── operations/
└── scripts/               ← Operational scripts
```

## Development Commands

```bash
# Start all services
make up

# Run backend tests
make test-backend

# Run frontend tests
make test-frontend

# Run integration tests (requires running services)
make test-integration

# Run scale tests
make test-scale

# Run database migrations
make migrate

# Seed development data
make seed

# View logs
make logs

# Stop everything
make down

# Full reset (destroy volumes)
make reset
```

## Coding Standards

### Python (Backend)

- Python 3.12+ with type hints on all function signatures
- Use `async def` for all database and HTTP operations
- SQLAlchemy 2.0 style (select(), async session)
- Pydantic v2 for all request/response schemas
- All services are classes instantiated with dependency injection
- Imports: stdlib → third-party → local, separated by blank lines
- Docstrings: Google style on all public methods
- Error handling: raise custom exceptions from `core/exceptions.py`, caught by FastAPI handlers
- Logging: use `structlog` with bound context (request_id, service_name)
- No bare `except:` — always catch specific exceptions
- No `print()` — use logger

### TypeScript (Frontend)

- Strict TypeScript — no `any` types except in rare escape hatches with `// eslint-disable-next-line`
- Functional components only (no class components)
- Hooks for all state management
- API calls exclusively through Tanstack Query hooks in `api/` directory
- Tailwind for styling — no inline styles, no CSS modules
- Component files: PascalCase (e.g., `SearchBar.tsx`)
- Utility files: camelCase (e.g., `formatDate.ts`)

### Database

- All tables have: `id UUID PRIMARY KEY`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`
- Use Alembic for ALL schema changes — never raw SQL in application code
- Foreign keys with appropriate ON DELETE behavior
- Indexes on all foreign keys and frequently queried columns
- Use `TIMESTAMPTZ` (not `TIMESTAMP`) for all datetime columns

### Testing

- Unit test files mirror source structure: `src/agentlake/services/search.py` → `tests/unit/test_services/test_search.py`
- Use pytest fixtures for shared setup
- Use Factory Boy for model factories
- Mock external dependencies (MinIO, LLM gateway, Redis) in unit tests
- Integration tests use real services via Docker Compose test profile
- Every public function has at least one test
- Test both happy path and error cases
- Coverage target: ≥ 85%

### API Design

- All endpoints under `/api/v1/` prefix
- Consistent response envelope: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`
- Error responses: RFC 7807 Problem Details format
- Pagination: cursor-based with `limit` and `cursor` parameters
- Sorting: `sort_by` and `sort_order` query parameters
- All list endpoints support filtering via query parameters

### Docker

- Multi-stage builds (builder + runtime)
- Non-root user in runtime stage
- Health check endpoints for all services
- Explicit resource limits in production compose
- Named volumes for all persistent data

## Environment Variables

See `.env.example` for the complete list. Key variables:

| Variable | Service | Description |
|----------|---------|-------------|
| `DATABASE_URL` | api, distiller, llm-gateway | PostgreSQL connection |
| `REDIS_URL` | api, distiller | Redis connection |
| `MINIO_ENDPOINT` | api, distiller | MinIO server |
| `MINIO_ACCESS_KEY` | api, distiller | MinIO credentials |
| `MINIO_SECRET_KEY` | api, distiller | MinIO credentials |
| `LLM_GATEWAY_URL` | api, distiller | Internal gateway URL |
| `LLM_GATEWAY_SERVICE_TOKEN` | all internal | Internal auth token |
| `ANTHROPIC_API_KEY` | llm-gateway ONLY | Anthropic provider key |
| `OPENROUTER_API_KEY` | llm-gateway ONLY | OpenRouter provider key |
| `OPENAI_COMPAT_BASE_URL` | llm-gateway ONLY | Self-hosted model URL |
| `LLM_DEFAULT_PROVIDER` | llm-gateway | Default provider (anthropic/openrouter) |
| `LLM_FALLBACK_CHAIN` | llm-gateway | Provider fallback order |
| `JWT_SECRET` | api | Session signing key |

## When Working on This Project

1. **Read the PRD first.** Every implementation decision should trace back to a requirement.
2. **Check AGENTS.md** for your scope boundaries. Don't implement outside your agent's scope.
3. **Run tests before committing.** `make test-backend` and `make test-frontend`.
4. **Update migrations** for any model changes. `cd backend && alembic revision --autogenerate -m "description"`.
5. **Keep the LLM gateway invariant.** If you need LLM capabilities, use `services/llm_client.py`.
6. **Citations are non-negotiable.** Every processed document must have working citation links.
7. **Write tests alongside implementation.** Not after. Tests validate your understanding of the requirements.

## Common Patterns

### Adding a new file adapter

```python
# backend/src/agentlake/adapters/my_format.py
from agentlake.adapters.base import FileAdapter, ExtractedContent, TextBlock

class MyFormatAdapter:
    supported_extensions = [".myf"]
    supported_mimetypes = ["application/x-myformat"]

    def can_handle(self, filename: str, content_type: str) -> bool:
        return Path(filename).suffix.lower() in self.supported_extensions

    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent:
        # Parse the file, return text blocks with source locators
        ...
```

The adapter is auto-discovered by the registry at startup.

### Adding an API endpoint

```python
# backend/src/agentlake/api/my_router.py
from fastapi import APIRouter, Depends
from agentlake.core.auth import require_role
from agentlake.schemas.my_schema import MyResponse

router = APIRouter(prefix="/api/v1/myresource", tags=["myresource"])

@router.get("/", response_model=MyResponse)
async def list_items(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_role("viewer")),
):
    ...
```

Register the router in `main.py`.

### Making an LLM call

```python
# ALWAYS use the LLM client, NEVER import anthropic/openrouter/any SDK directly
from agentlake.services.llm_client import LLMClient

async def my_service_method(self, llm: LLMClient):
    response = await llm.complete(
        messages=[{"role": "user", "content": prompt}],
        purpose="my_task_name",  # used for task routing AND token ledger tracking
        # model and provider are resolved automatically via task routing config
        # but can be overridden explicitly:
        # model="claude-sonnet-4-20250514",
        # provider="openrouter",  # force a specific provider
    )
    return response.content
```

The `purpose` field is the key to the routing system — it maps to a model via the `task_routing` config, which maps to a provider via pattern matching. You almost never need to specify `model` or `provider` directly.

### Adding a new LLM provider

```python
# backend/src/agentlake/llm_gateway/providers/my_provider.py
from agentlake.llm_gateway.providers.base import LLMProvider, ProviderResponse

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

Then add env vars to `.env.example` and register in the provider config. No changes to gateway core or calling services.

## Performance Targets (from PRD)

| Metric | Target |
|--------|--------|
| Keyword search p95 | < 100ms at 1M docs |
| Semantic search p95 | < 200ms at 1M docs |
| Hybrid search p95 | < 250ms at 1M docs |
| File upload throughput | 50 files/min |
| Processing latency | < 60s per file |
| API response (non-search) | < 50ms p95 |
| UI initial load | < 2s |
| Concurrent connections | 500+ |

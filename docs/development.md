# Development Guide

## Clone and Setup

```bash
git clone <repo-url> agentlake
cd agentlake
```

## Backend Setup

### Prerequisites

- Python 3.12+
- A running PostgreSQL 16 instance with pgvector and AGE extensions (or use Docker Compose)

### Install dependencies

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure environment

```bash
cp .env.example .env
# Edit .env: set DATABASE_URL, REDIS_URL, MINIO_*, and at least one LLM provider key
```

### Start infrastructure with Docker Compose

The simplest approach is to run infrastructure services via Docker Compose while developing the backend locally:

```bash
# From the project root
docker compose up -d postgres redis minio
```

### Run database migrations

```bash
cd backend
alembic upgrade head
```

### Start the API server (development mode with hot reload)

```bash
uvicorn agentlake.main:app --host 0.0.0.0 --port 8000 --reload
```

### Start the LLM Gateway

```bash
uvicorn agentlake.llm_gateway.app:app --host 0.0.0.0 --port 8001 --reload
```

### Start Celery workers

```bash
celery -A agentlake.workers.celery_app worker --loglevel=info --concurrency=4 -Q high,default,low
```

### Start the MCP server

```bash
python -m agentlake.mcp.server --transport sse --port 8002
```

## Frontend Setup

### Prerequisites

- Node.js 20+
- npm 10+

### Install dependencies

```bash
cd frontend
npm install
```

### Configure environment

The frontend reads `VITE_API_URL` and `VITE_WS_URL` at build time:

```bash
# These default to localhost in dev mode
export VITE_API_URL=http://localhost:8000
export VITE_WS_URL=ws://localhost:8000/ws
```

### Start development server

```bash
npm run dev
```

The UI will be available at http://localhost:5173 (Vite default) or http://localhost:3000 if configured.

## Running Tests

### Backend unit tests

```bash
make test-backend
# or directly:
cd backend && python -m pytest tests/unit/ -v --tb=short
```

### Backend integration tests

Requires running services (PostgreSQL, Redis, MinIO):

```bash
make test-integration
```

### Frontend tests

```bash
make test-frontend
# or directly:
cd frontend && npm test
```

### All tests

```bash
make test
```

### Scale/load tests

```bash
make test-scale
```

## Code Style

### Backend

- **Formatter:** ruff format
- **Linter:** ruff check
- **Type hints:** Required on all function signatures
- **Docstrings:** Google style on all public methods
- **Imports:** stdlib, then third-party, then local (separated by blank lines)

```bash
make fmt-backend    # auto-format
make lint-backend   # lint check
```

### Frontend

- **Formatter:** Prettier
- **Linter:** ESLint with strict TypeScript rules
- **No `any` types** except with explicit eslint-disable comment
- **Functional components only** (no class components)

```bash
make fmt-frontend   # auto-format
make lint-frontend  # lint check
```

## Project Structure Quick Reference

### Backend source (`backend/src/agentlake/`)

| Directory | Purpose |
|-----------|---------|
| `adapters/` | File format parsers (PDF, DOCX, etc.) |
| `api/` | FastAPI route handlers |
| `core/` | Auth, exceptions, database session |
| `llm_gateway/` | LLM Gateway service (separate app) |
| `mcp/` | MCP server for Claude Desktop/Code |
| `models/` | SQLAlchemy ORM models |
| `prompts/` | LLM prompt templates |
| `schemas/` | Pydantic request/response schemas |
| `services/` | Business logic services |
| `workers/` | Celery task definitions |

### Frontend source (`frontend/src/`)

| Directory | Purpose |
|-----------|---------|
| `api/` | Tanstack Query hooks for API calls |
| `components/` | Reusable React components |
| `pages/` | Route-level page components |
| `stores/` | Zustand state stores |
| `utils/` | Utility functions |

## Adding New Features

### New file adapter

1. Create `backend/src/agentlake/adapters/my_format.py`
2. Implement the `FileAdapter` interface
3. The adapter registry auto-discovers it at startup
4. Add tests in `backend/tests/unit/test_adapters/`

### New API endpoint

1. Create or edit a router in `backend/src/agentlake/api/`
2. Add Pydantic schemas in `backend/src/agentlake/schemas/`
3. Register the router in `main.py`
4. Add tests in `backend/tests/unit/test_api/`

### New LLM provider

1. Create `backend/src/agentlake/llm_gateway/providers/my_provider.py`
2. Implement the `LLMProvider` interface
3. Add env vars to `.env.example`
4. Register in provider config
5. No changes needed to gateway core or calling services

## Database Migrations

All schema changes go through Alembic:

```bash
cd backend

# Generate a migration from model changes
alembic revision --autogenerate -m "add foo column to bar table"

# Apply migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# View migration history
alembic history
```

## Useful Make Targets

```bash
make help          # list all targets
make up            # start all services
make down          # stop all services
make logs          # tail all service logs
make build         # rebuild Docker images
make reset         # destroy volumes and recreate from scratch
make shell-api     # bash into API container
make shell-db      # psql into database
make backup        # run backup script
```

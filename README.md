# AgentLake

A distributed, containerized, agent-friendly data lake that ingests raw unstructured files, processes them through an LLM-powered pipeline into searchable markdown with citation traceability, and serves results through a REST API, React UI, and MCP server.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    React UI (:5173)                      │
│  Dashboard │ Search │ Vault │ Graph │ Knowledge │ Admin  │
├─────────────────────────────────────────────────────────┤
│                  FastAPI REST API (:8010)                │
│     Vault │ Query │ Graph │ Discover │ Admin │ Stream    │
├──────────────┬──────────────────────────────────────────┤
│ LLM Gateway  │        LangGraph Pipelines               │
│   (:8011)    │  Per-Document (GPT-5.4 single-pass)      │
│              │  Cross-Document Intelligence              │
│  OpenRouter  │  Folder Analysis + Parent Rollup          │
│  Anthropic   │  Agentic Search + Knowledge Memory        │
│  OpenAI-compat│  Autonomous Exploration                  │
├──────────────┴──────────────────────────────────────────┤
│  PostgreSQL+pgvector+AGE │ Redis │ MinIO │ WebDAV(:8008) │
└─────────────────────────────────────────────────────────┘
```

## Key Features

- **GPT-5.4 Single-Pass Extraction** — entire documents analyzed in one LLM call: ~49 entities/doc, ~28 relationships/doc, ~25 tags/doc, people with contact details, dates, metrics, cross-references
- **LangGraph Pipelines** — stateful, parallelized document processing with conditional branching
- **Hybrid Search** — keyword (tsvector) + semantic (pgvector) + Reciprocal Rank Fusion
- **Agentic Search** — ask natural language questions, get synthesized answers with cited sources
- **Institutional Knowledge** — questions grow organizational memory; system autonomously explores follow-ups
- **Folder Hierarchy** — organize files in folders with per-folder AI summaries and parent rollups
- **WebDAV Network Drive** — mount the vault in Finder/Explorer; file changes auto-trigger processing
- **Entity Graph** — entities and relationships queryable via API, visualized in D3.js
- **Citation Traceability** — every processed claim links back to raw source chunks
- **MCP Server** — expose AgentLake as an MCP server for Claude Desktop/Code

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Celery 5, LangGraph |
| Database | PostgreSQL 16 + pgvector + Apache AGE |
| Object Storage | MinIO (S3-compatible) |
| Frontend | React 18, TypeScript, Vite, TailwindCSS, Tanstack Query/Router |
| LLM | GPT-5.4 via OpenRouter (1M context, 128K output) |
| Network Drive | WebDAV (WsgiDAV + Cheroot) |
| Containers | Docker Compose (dev), Kubernetes (prod) |

## Quick Start

```bash
# Clone
git clone git@github.com:capaulson/agentlake.git && cd agentlake

# Start infrastructure
docker compose up -d postgres redis minio

# Install backend
python3.12 -m venv .venv && source .venv/bin/activate
cd backend && pip install -e ".[dev]" && cd ..

# Configure
cp .env.example .env  # Edit with your OpenRouter API key

# Run migrations
cd backend && alembic upgrade head && cd ..

# Start all services
uvicorn agentlake.main:app --port 8010 --app-dir backend/src          # API
uvicorn agentlake.llm_gateway.app:app --port 8011 --app-dir backend/src  # LLM Gateway
celery -A agentlake.workers.celery_app worker --concurrency=10           # Workers
python -m agentlake.webdav --port 8008                                   # WebDAV
cd frontend && npm install && npm run dev                                # UI (:5173)
```

## Processing Pipeline

```
Upload → Extract → Chunk → GPT-5.4 Single-Pass Analysis → Cite → Embed → Store
                              ↓
                    title, summary, category (99% accuracy)
                    ~49 entities, ~28 relationships per doc
                    people with emails/phones/roles
                    ~25 tags, dates, metrics, key quotes
                    section-by-section breakdown
```

## License

MIT — see [LICENSE](LICENSE)

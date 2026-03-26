# Architecture Deep Dive: AgentLake

## Technical Design Decisions & Data Flow

---

## 1. Data Flow: Upload to Query

```
User/Agent                    AgentLake System
    │
    ├── POST /vault/upload ──→ [API Server]
    │                            │
    │                            ├── Validate file type + size
    │                            ├── Compute SHA-256 hash
    │                            ├── Check dedup (hash exists?)
    │                            ├── Store blob → MinIO
    │                            ├── Insert File record → PostgreSQL
    │                            ├── Create FileTag records
    │                            ├── Set status = "pending"
    │                            └── Enqueue task → Redis/Celery
    │                                     │
    │                                     ▼
    │                              [Distiller Worker]
    │                                     │
    │                            ┌────────┴────────┐
    │                            │  Stage 1: Extract │
    │                            │  (FileAdapter)    │
    │                            └────────┬────────┘
    │                                     │
    │                            ┌────────┴────────┐
    │                            │  Stage 2: Chunk   │
    │                            │  (semantic split)  │
    │                            └────────┬────────┘
    │                                     │
    │                            ┌────────┴────────┐
    │                            │  Stage 3: Summarize│
    │                            │  (LLM via 4B)      │──→ [LLM Gateway] ──→ Claude API
    │                            └────────┬────────┘
    │                                     │
    │                            ┌────────┴────────┐
    │                            │  Stage 4: Cite     │
    │                            │  (link to source)  │
    │                            └────────┬────────┘
    │                                     │
    │                            ┌────────┴────────┐
    │                            │  Stage 5: Ontology │
    │                            │  (classify + tag)   │──→ [LLM Gateway] ──→ Claude API
    │                            └────────┬────────┘
    │                                     │
    │                            ┌────────┴────────┐
    │                            │  Stage 6: Store    │
    │                            │  + embed (via 4B)  │──→ [LLM Gateway] ──→ Embed API
    │                            └────────┬────────┘
    │                                     │
    │                            ┌────────┴────────┐
    │                            │  PostgreSQL:        │
    │                            │  - ProcessedDocument│
    │                            │  - DocumentChunk    │
    │                            │  - Citation         │
    │                            │  - DiffLog          │
    │                            └─────────────────┘
    │
    ├── GET /query/search ───→ [API Server]
    │                            │
    │                            ├── Parse query + filters
    │                            ├── Generate query embedding (via 4B)
    │                            ├── Execute hybrid search
    │                            │   ├── Full-text: tsvector query
    │                            │   ├── Semantic: pgvector cosine
    │                            │   └── RRF score fusion
    │                            └── Return ranked results
    │
    └── Response ←───────────────┘
```

---

## 2. Database Schema (PostgreSQL)

### 2.1 Extensions Required

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgvector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- trigram for fuzzy text search
```

### 2.2 Core Tables

```sql
-- Layer 1: Raw Storage
CREATE TABLE files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename VARCHAR(512) NOT NULL,
    original_filename VARCHAR(512) NOT NULL,
    content_type VARCHAR(255) NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256_hash VARCHAR(64) NOT NULL,
    storage_key VARCHAR(1024) NOT NULL UNIQUE,
    uploaded_by VARCHAR(255) NOT NULL DEFAULT 'system',
    status VARCHAR(50) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'processed', 'error', 'deleted')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_files_hash ON files(sha256_hash);
CREATE INDEX idx_files_status ON files(status);
CREATE INDEX idx_files_created ON files(created_at DESC);

CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tags_name ON tags(name);

CREATE TABLE file_tags (
    file_id UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by VARCHAR(255) NOT NULL DEFAULT 'system',
    PRIMARY KEY (file_id, tag_id)
);

-- Layer 3: Processed Data
CREATE TABLE processed_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_file_id UUID NOT NULL REFERENCES files(id),
    title VARCHAR(1024) NOT NULL,
    summary TEXT NOT NULL,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(255),
    body_markdown TEXT NOT NULL,
    frontmatter JSONB NOT NULL DEFAULT '{}',
    entities JSONB NOT NULL DEFAULT '[]',
    embedding vector(1536),
    version INT NOT NULL DEFAULT 1,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Full-text search vector
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body_markdown, '')), 'C')
    ) STORED
);

CREATE INDEX idx_docs_source ON processed_documents(source_file_id);
CREATE INDEX idx_docs_category ON processed_documents(category);
CREATE INDEX idx_docs_current ON processed_documents(is_current) WHERE is_current = TRUE;
CREATE INDEX idx_docs_search ON processed_documents USING GIN(search_vector);
CREATE INDEX idx_docs_embedding ON processed_documents USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_docs_entities ON processed_documents USING GIN(entities);

CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES processed_documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    source_locator VARCHAR(512),
    token_count INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chunks_doc ON document_chunks(document_id, chunk_index);
CREATE INDEX idx_chunks_embedding ON document_chunks USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE citations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES processed_documents(id) ON DELETE CASCADE,
    citation_index INT NOT NULL,
    source_file_id UUID NOT NULL REFERENCES files(id),
    chunk_index INT NOT NULL,
    source_locator VARCHAR(512),
    quote_snippet VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_citations_doc ON citations(document_id, citation_index);

-- Diff/Change Logs
CREATE TABLE diff_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES processed_documents(id) ON DELETE CASCADE,
    source_file_id UUID REFERENCES files(id),
    diff_type VARCHAR(50) NOT NULL
        CHECK (diff_type IN ('initial_processing', 'reprocessing', 'human_edit', 'agent_edit')),
    before_text TEXT,
    after_text TEXT NOT NULL,
    justification TEXT NOT NULL,
    created_by VARCHAR(255) NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_diffs_doc ON diff_logs(document_id, created_at DESC);

-- Layer 4B: LLM Token Ledger
CREATE TABLE llm_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    caller_service VARCHAR(100) NOT NULL,
    caller_task_id UUID,
    purpose VARCHAR(255) NOT NULL,
    model VARCHAR(100) NOT NULL,
    provider VARCHAR(100) NOT NULL,      -- which provider adapter handled this
    request_type VARCHAR(50) NOT NULL CHECK (request_type IN ('completion', 'embedding')),
    input_tokens INT NOT NULL,
    output_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL,
    estimated_cost_usd NUMERIC(10, 6) NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL,
    status VARCHAR(50) NOT NULL
        CHECK (status IN ('success', 'error', 'timeout', 'rate_limited', 'fallback')),
    fallback_from VARCHAR(100),          -- if fallback, which provider failed first
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_llm_service ON llm_requests(caller_service, created_at DESC);
CREATE INDEX idx_llm_provider ON llm_requests(provider, created_at DESC);
CREATE INDEX idx_llm_created ON llm_requests(created_at DESC);

-- Materialized view for usage dashboards (now includes provider + cost)
CREATE MATERIALIZED VIEW llm_usage_summary AS
SELECT
    date_trunc('hour', created_at) AS hour,
    caller_service,
    provider,
    model,
    COUNT(*) AS request_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(total_tokens) AS total_tokens,
    SUM(estimated_cost_usd) AS total_cost_usd,
    AVG(latency_ms)::INT AS avg_latency_ms,
    COUNT(*) FILTER (WHERE status != 'success') AS error_count,
    COUNT(*) FILTER (WHERE status = 'fallback') AS fallback_count
FROM llm_requests
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX idx_usage_summary ON llm_usage_summary(hour, caller_service, provider, model);

-- Auth
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key_hash VARCHAR(128) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer'
        CHECK (role IN ('admin', 'editor', 'viewer', 'agent')),
    rate_limit INT NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);
```

---

## 3. Search Architecture

### 3.1 Hybrid Search Implementation

```python
async def hybrid_search(
    query: str,
    filters: SearchFilters,
    keyword_weight: float = 0.4,
    semantic_weight: float = 0.6,
    limit: int = 20,
    offset: int = 0,
) -> SearchResults:
    # Generate query embedding via Layer 4B
    query_embedding = await llm_client.embed(query)

    # Build filter CTE
    filter_cte = build_filter_cte(filters)

    # Execute both searches in parallel
    sql = f"""
    WITH filtered AS ({filter_cte}),
    keyword_results AS (
        SELECT d.id,
               ts_rank_cd(d.search_vector, plainto_tsquery('english', :query)) AS keyword_score,
               ROW_NUMBER() OVER (ORDER BY ts_rank_cd(d.search_vector, plainto_tsquery('english', :query)) DESC) AS keyword_rank
        FROM processed_documents d
        JOIN filtered f ON d.id = f.id
        WHERE d.search_vector @@ plainto_tsquery('english', :query)
          AND d.is_current = TRUE
        LIMIT 100
    ),
    semantic_results AS (
        SELECT d.id,
               1 - (d.embedding <=> :embedding) AS semantic_score,
               ROW_NUMBER() OVER (ORDER BY d.embedding <=> :embedding) AS semantic_rank
        FROM processed_documents d
        JOIN filtered f ON d.id = f.id
        WHERE d.is_current = TRUE
        LIMIT 100
    ),
    rrf AS (
        SELECT COALESCE(k.id, s.id) AS id,
               :kw * COALESCE(1.0 / (60 + k.keyword_rank), 0) +
               :sw * COALESCE(1.0 / (60 + s.semantic_rank), 0) AS rrf_score
        FROM keyword_results k
        FULL OUTER JOIN semantic_results s ON k.id = s.id
    )
    SELECT r.rrf_score, d.*
    FROM rrf r
    JOIN processed_documents d ON r.id = d.id
    ORDER BY r.rrf_score DESC
    LIMIT :limit OFFSET :offset
    """
```

### 3.2 Index Tuning

- HNSW parameters: `m=16, ef_construction=64` (build), `ef_search=40` (query)
- GIN index on `search_vector` for full-text
- BRIN index on `created_at` for time-range queries
- Partial index on `is_current = TRUE` to exclude old versions

---

## 4. LLM Gateway Design (Modular Provider Architecture)

### 4.1 Request Flow

```
Internal Service
    │
    ├── POST /llm/complete
    │   Headers: X-Service-Token: <internal-token>
    │   Body: {model, messages, provider (optional), caller_service, purpose, ...}
    │
    ▼
[LLM Gateway Core]
    │
    ├── 1. Validate service token
    ├── 2. Check rate limit for caller_service
    ├── 3. Resolve provider:
    │       a. Explicit provider in request? → use it
    │       b. Task routing table (purpose → model)? → use mapped model
    │       c. Model pattern matching (e.g. "claude-*" → anthropic) → select provider
    ├── 4. Get provider adapter from registry
    ├── 5. Call provider.complete() or provider.embed()
    │       ├── On success → normalize response via ProviderResponse
    │       └── On failure → check fallback_chain → try next provider
    ├── 6. Compute estimated cost from pricing table
    ├── 7. Record to token ledger (async, non-blocking)
    ├── 8. Return normalized response with usage + provider metadata
    │
    ▼
Response to caller
```

### 4.2 Provider Adapter Pattern

```python
# llm_gateway/providers/base.py

from dataclasses import dataclass
from typing import Protocol

@dataclass
class ProviderResponse:
    """Normalized response — every provider returns this exact shape."""
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    raw_response: dict    # original provider payload for debugging

@dataclass
class ModelInfo:
    model_id: str
    display_name: str
    provider: str
    supports_completion: bool
    supports_embedding: bool
    context_window: int
    pricing_input_per_1m: float
    pricing_output_per_1m: float

@dataclass
class ProviderHealth:
    provider: str
    healthy: bool
    latency_ms: int | None
    error: str | None
    quota_remaining: int | None   # from provider rate-limit headers

class LLMProvider(Protocol):
    """Every provider adapter implements this interface."""

    provider_name: str

    async def complete(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.3,
        system: str | None = None,
        **kwargs,
    ) -> ProviderResponse: ...

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]: ...

    def list_models(self) -> list[ModelInfo]: ...

    async def health_check(self) -> ProviderHealth: ...
```

### 4.3 Built-In Providers

```python
# llm_gateway/providers/anthropic.py
class AnthropicProvider:
    """Direct Anthropic API. Lowest latency for Claude models."""
    provider_name = "anthropic"

    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, model, messages, **kw) -> ProviderResponse:
        resp = await self.client.messages.create(
            model=model, messages=messages,
            max_tokens=kw.get("max_tokens", 4096),
            temperature=kw.get("temperature", 0.3),
            system=kw.get("system"),
        )
        return ProviderResponse(
            content=resp.content[0].text,
            model=resp.model,
            provider=self.provider_name,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            raw_response=resp.model_dump(),
        )

    async def embed(self, texts, model=None) -> list[list[float]]:
        # Anthropic doesn't have native embeddings; delegate to configured embed provider
        raise NotImplementedError("Use embedding_provider for embeddings")


# llm_gateway/providers/openrouter.py
class OpenRouterProvider:
    """OpenRouter — access any model through a single API key."""
    provider_name = "openrouter"

    def __init__(self, api_key: str, site_name: str = "AgentLake"):
        self.api_key = api_key
        self.base_url = "https://openrouter.ai/api/v1"
        self.site_name = site_name

    async def complete(self, model, messages, **kw) -> ProviderResponse:
        # OpenRouter uses OpenAI-compatible format
        # Transform Anthropic-style messages if needed
        payload = {
            "model": model,
            "messages": self._normalize_messages(messages, kw.get("system")),
            "max_tokens": kw.get("max_tokens", 4096),
            "temperature": kw.get("temperature", 0.3),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": f"https://agentlake.dev",
            "X-Title": self.site_name,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload, headers=headers, timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]
        usage = data.get("usage", {})
        return ProviderResponse(
            content=choice["content"],
            model=data.get("model", model),
            provider=self.provider_name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            raw_response=data,
        )

    async def embed(self, texts, model=None) -> list[list[float]]:
        model = model or "openai/text-embedding-3-small"
        # ... OpenRouter embedding endpoint


# llm_gateway/providers/openai_compat.py
class OpenAICompatProvider:
    """Generic OpenAI-compatible endpoint (vLLM, Ollama, LM Studio, etc.)."""
    provider_name = "openai_compat"

    def __init__(self, api_key: str | None, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
    # Same OpenAI-compatible format as OpenRouter, different base_url
```

### 4.4 Provider Registry

```python
# llm_gateway/providers/registry.py
import re

class ProviderRegistry:
    """Manages provider adapters, model routing, and fallback chains."""

    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}
        self._model_patterns: list[tuple[re.Pattern, str]] = []  # (pattern, provider_name)
        self._task_routing: dict[str, str] = {}                   # purpose → model
        self._fallback_chain: list[str] = []
        self._pricing: dict[tuple[str, str], dict] = {}           # (provider, model) → {input, output}

    def register_provider(self, provider: LLMProvider) -> None:
        self._providers[provider.provider_name] = provider

    def add_model_route(self, pattern: str, provider_name: str) -> None:
        """Route models matching glob pattern to a provider."""
        regex = re.compile(pattern.replace("*", ".*"))
        self._model_patterns.append((regex, provider_name))

    def resolve_provider(
        self, model: str | None, provider: str | None, purpose: str | None
    ) -> tuple[LLMProvider, str]:
        """
        Returns (provider_adapter, resolved_model).
        Resolution order:
        1. Explicit provider name → use it
        2. purpose → task_routing → model → pattern match
        3. model → pattern match against registered routes
        """
        # 1. Explicit provider
        if provider and provider in self._providers:
            resolved_model = model or self._task_routing.get(purpose, "")
            return self._providers[provider], resolved_model

        # 2. Task routing
        resolved_model = model
        if not resolved_model and purpose:
            resolved_model = self._task_routing.get(purpose)
        if not resolved_model:
            raise ValueError(f"Cannot resolve model: no model, no task routing for purpose={purpose}")

        # 3. Pattern match
        for regex, pname in self._model_patterns:
            if regex.fullmatch(resolved_model):
                return self._providers[pname], resolved_model

        raise ValueError(f"No provider registered for model: {resolved_model}")

    def get_fallback_provider(
        self, failed_provider: str, model: str
    ) -> tuple[LLMProvider, str] | None:
        """Get next provider in fallback chain."""
        try:
            idx = self._fallback_chain.index(failed_provider)
            for next_name in self._fallback_chain[idx + 1:]:
                if next_name in self._providers:
                    return self._providers[next_name], model
        except ValueError:
            pass
        return None

    def estimate_cost(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
        key = (provider, model)
        if key not in self._pricing:
            return 0.0
        p = self._pricing[key]
        return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
```

### 4.5 Configuration

Provider configuration is loaded from environment variables and an optional YAML file:

```python
# llm_gateway/config.py

class GatewayConfig(BaseSettings):
    # Provider API keys (all optional — at least one required)
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    openai_compat_api_key: str | None = None
    openai_compat_base_url: str | None = None

    # Config file path for advanced routing
    provider_config_path: str = "/app/config/llm_providers.yaml"

    # Defaults
    default_completion_model: str = "claude-sonnet-4-20250514"
    default_embedding_model: str = "voyage-3"
    default_provider: str = "anthropic"

    # Fallback
    fallback_enabled: bool = True
    fallback_chain: list[str] = ["anthropic", "openrouter"]

    # Internal auth
    service_token: str

    # Rate limiting
    global_rpm: int = 300
    per_service_rpm: int = 100
    per_provider_rpm: dict[str, int] = {"anthropic": 300, "openrouter": 200}

    class Config:
        env_prefix = "LLM_"
```

### 4.6 Token Counting

- Pre-request: estimate input tokens using tiktoken/anthropic tokenizer
- Post-request: use actual token counts from provider response
- Ledger records actual counts from the provider
- Cost estimation uses the pricing table keyed by (provider, model)
- OpenRouter includes cost in its response headers — these are captured and logged alongside estimates

### 4.7 Message Format Normalization

Different providers expect different message formats. The gateway normalizes transparently:

```python
# llm_gateway/providers/format.py

def anthropic_to_openai(messages: list[dict], system: str | None) -> list[dict]:
    """Convert Anthropic-style messages to OpenAI/OpenRouter format."""
    result = []
    if system:
        result.append({"role": "system", "content": system})
    for msg in messages:
        # Handle Anthropic's content blocks → OpenAI plain text
        if isinstance(msg.get("content"), list):
            text_parts = [b["text"] for b in msg["content"] if b.get("type") == "text"]
            result.append({"role": msg["role"], "content": "\n".join(text_parts)})
        else:
            result.append(msg)
    return result

def openai_to_anthropic(messages: list[dict]) -> tuple[list[dict], str | None]:
    """Convert OpenAI-style messages to Anthropic format. Extract system message."""
    system = None
    converted = []
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"]
        else:
            converted.append(msg)
    return converted, system
```

The internal API accepts **Anthropic-style** messages as the canonical format (since it's our primary provider). Provider adapters handle conversion internally.

---

## 5. File Adapter System

### 5.1 Adapter Protocol

```python
@dataclass
class ExtractedContent:
    text_blocks: list[TextBlock]
    metadata: dict[str, Any]
    structure: list[StructureMarker]  # headings, page breaks, table boundaries

@dataclass
class TextBlock:
    content: str
    block_type: str  # paragraph, heading, table, list, code, caption
    position: int    # ordinal position in document
    source_locator: str  # "page 3", "slide 7", "sheet:A1:D10", "line 45"

class FileAdapter(Protocol):
    supported_extensions: list[str]
    supported_mimetypes: list[str]

    def can_handle(self, filename: str, content_type: str) -> bool: ...
    def extract(self, file_bytes: bytes, filename: str) -> ExtractedContent: ...
```

### 5.2 Adapter Registry

```python
class AdapterRegistry:
    _adapters: dict[str, FileAdapter] = {}

    def register(self, adapter: FileAdapter) -> None:
        for ext in adapter.supported_extensions:
            self._adapters[ext.lower()] = adapter

    def get_adapter(self, filename: str) -> FileAdapter | None:
        ext = Path(filename).suffix.lower()
        return self._adapters.get(ext)

    def supported_extensions(self) -> list[str]:
        return sorted(self._adapters.keys())
```

Auto-discovery at startup scans `agentlake/adapters/` for classes implementing `FileAdapter`.

---

## 6. Chunking Strategy

```python
class SemanticChunker:
    def __init__(self, max_tokens: int = 1024, overlap_tokens: int = 64):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, text_blocks: list[TextBlock]) -> list[Chunk]:
        """
        1. Respect structural boundaries (don't split mid-table, mid-code-block)
        2. Split on paragraph boundaries when possible
        3. Fall back to sentence boundaries for oversized paragraphs
        4. Maintain overlap for context continuity
        5. Each chunk retains source_locator from its text blocks
        """
```

---

## 7. Citation Format

Citations are embedded in processed markdown as numbered references:

```markdown
The robot arm achieves 0.1mm repeatability in structured environments [1].
However, unstructured environments require adaptive control strategies [2][3].

---
## Citations

[1]: [Source: meeting-notes-2026-03-15.pdf, page 7, section 2.3](/api/v1/vault/files/abc123/download#chunk=3)
[2]: [Source: technical-spec-v2.docx, page 12](/api/v1/vault/files/def456/download#chunk=7)
[3]: [Source: research-paper.pdf, page 4, Abstract](/api/v1/vault/files/ghi789/download#chunk=1)
```

The citation URL pattern `/api/v1/vault/files/{file_id}/download#chunk={chunk_index}` allows:
- Direct download of the raw source file
- UI can highlight the specific chunk when the `#chunk=N` fragment is present
- External agents can programmatically trace any claim to its source

---

## 8. Environment Configuration

All configuration via environment variables with sensible defaults:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://agentlake:password@postgres:5432/agentlake
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=agentlake
MINIO_SECRET_KEY=changeme
MINIO_BUCKET=agentlake-vault
MINIO_SECURE=false

# Redis
REDIS_URL=redis://redis:6379/0

# LLM Gateway
LLM_GATEWAY_URL=http://llm-gateway:8001
LLM_GATEWAY_SERVICE_TOKEN=internal-secret-token

# LLM Provider (only in gateway service)
ANTHROPIC_API_KEY=sk-ant-...
LLM_DEFAULT_MODEL=claude-sonnet-4-20250514
LLM_EMBEDDING_MODEL=voyage-3

# Processing
DISTILLER_CONCURRENCY=4
DISTILLER_MAX_RETRIES=3
DISTILLER_CHUNK_SIZE=1024

# API
API_HOST=0.0.0.0
API_PORT=8000
API_CORS_ORIGINS=http://localhost:3000
JWT_SECRET=changeme
API_KEY_SALT=changeme

# UI
VITE_API_URL=http://localhost:8000
```

---

## 9. Deployment Topology

### 9.1 Development (Docker Compose)

All services on a single host. Hot-reload enabled. Ports exposed for debugging.

### 9.2 Production (Kubernetes)

```
Ingress (TLS) ─→ agentlake-api (HPA: 2-8 pods)
                  agentlake-ui  (2 pods, Nginx)
                  
Internal only:    agentlake-distiller (HPA: 2-16 pods based on queue depth)
                  agentlake-llm-gateway (2 pods, no HPA - rate limited by provider)
                  
StatefulSets:     PostgreSQL (1 primary, optional read replica)
                  Redis (1 primary)
                  MinIO (1+ nodes, erasure coding for production)

NetworkPolicy:    Only llm-gateway can egress to LLM provider domains
                  (api.anthropic.com, openrouter.ai, and configured custom endpoints)
                  All other pods: internal-only egress
```

---

## 10. Entity Relationship Graph (Apache AGE)

See `specs/ENTITY_GRAPH.md` for full specification.

### 10.1 PostgreSQL Extensions

```sql
-- Required extensions (initialized in infra/postgres/init-extensions.sql)
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- trigram search
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- UUID generation
CREATE EXTENSION IF NOT EXISTS age;         -- Apache AGE graph
LOAD 'age';

SELECT ag_catalog.create_graph('agentlake_graph');
```

### 10.2 Graph Operations (Cypher via AGE)

```sql
-- Create an entity vertex
SELECT * FROM cypher('agentlake_graph', $$
    CREATE (e:Entity {
        id: $id,
        name: $name,
        canonical_name: $canonical_name,
        type: $type,
        document_count: 1
    })
    RETURN e
$$, $params) AS (e agtype);

-- Create a relationship edge
SELECT * FROM cypher('agentlake_graph', $$
    MATCH (a:Entity {canonical_name: $source}), (b:Entity {canonical_name: $target})
    CREATE (a)-[r:RELATED_TO {
        relationship_type: $rel_type,
        description: $description,
        confidence: $confidence,
        source_document_id: $doc_id,
        weight: 1
    }]->(b)
    RETURN r
$$, $params) AS (r agtype);

-- Traverse neighbors (depth 2)
SELECT * FROM cypher('agentlake_graph', $$
    MATCH (n:Entity {canonical_name: $name})-[r*1..2]-(m:Entity)
    RETURN n, r, m
$$, $params) AS (n agtype, r agtype, m agtype);

-- Shortest path
SELECT * FROM cypher('agentlake_graph', $$
    MATCH p = shortestPath(
        (a:Entity {canonical_name: $from})-[*]-(b:Entity {canonical_name: $to})
    )
    RETURN p
$$, $params) AS (p agtype);
```

### 10.3 Graph Data Flow

```
Layer 2 Pipeline (Stage 5a + 5b)
    │
    ├── Extract entities (existing) ──→ entity list
    ├── Extract relationships (NEW, LLM call via 4B)
    │       ──→ [{source, target, type, description, confidence}]
    │
    ▼
Graph Service
    │
    ├── canonicalize(entity_name) ──→ lowercase, strip suffixes
    ├── Upsert entity vertex (dedup by canonical_name)
    ├── Upsert relationship edge (increment weight if exists)
    └── Add MENTIONED_IN edge (document → entity)
```

---

## 11. Incremental Reprocessing

See `specs/INCREMENTAL_REPROCESSING.md` for full specification.

### 11.1 Chunk Comparison Flow

```
Re-upload / Reprocess
    │
    ▼
[Extract + Chunk] ──→ new_chunks (with content hashes)
    │
    ▼
[Load existing chunks from DB] ──→ old_chunks (with stored content hashes)
    │
    ▼
[compute_chunk_delta()]
    │
    ├── Hash match?  ──→ UNCHANGED (reuse summary + embedding, 0 LLM calls)
    ├── Jaccard > 0.85? → MODIFIED  (re-summarize + re-embed, 1 LLM call)
    ├── No match (new) → ADDED     (full summarize + embed, 1 LLM call)
    └── No match (old) → REMOVED   (mark removed from index)
    │
    ▼
[Reassemble document from old + new summaries]
    │
    ▼
[Store new version + diff log with chunk delta metadata]
```

### 11.2 Data Model Addition

```sql
-- Add content hash to chunks for incremental comparison
ALTER TABLE document_chunks ADD COLUMN content_hash VARCHAR(64) NOT NULL DEFAULT '';
CREATE INDEX idx_chunks_hash ON document_chunks(content_hash);

-- Add metadata JSONB to diff_logs for chunk delta tracking
ALTER TABLE diff_logs ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}';
```

---

## 12. SSE Streaming Architecture

See `specs/STREAMING.md` for full specification.

```
Processing Pipeline                       API Server                      UI
    │                                        │                             │
    ├── Stage update ──→ Redis Pub/Sub       │                             │
    │                    channel:             │                             │
    │                    processing:{file_id} │                             │
    │                         │               │                             │
    │                         └──→ SSE endpoint ──→ EventSource ──→ render
    │                                        │                             │
    │                                        │     WebSocket               │
    │                                        ├──→ /ws/dashboard ──→ live stats
    │                                        │                             │
    │                                        │     SSE                     │
    │                                        └──→ /stream/search ──→ results
```

---

## 13. MCP Server Architecture

See `specs/MCP_SERVER.md` for full specification.

```
Claude Desktop / Claude Code / MCP Client
    │
    ├── MCP Protocol (stdio or SSE)
    │
    ▼
[AgentLake MCP Server]  (:8002)
    │
    ├── agentlake_search     ──→ GET  /api/v1/query/search
    ├── agentlake_discover   ──→ GET  /api/v1/discover
    ├── agentlake_get_doc    ──→ GET  /api/v1/query/documents/{id}
    ├── agentlake_upload     ──→ POST /api/v1/vault/upload
    ├── agentlake_graph      ──→ GET  /api/v1/graph/entity/{id}/neighbors
    └── ...
    │
    ▼
[AgentLake API Server]  (:8000)
    │
    (standard auth, rate limiting, token ledger)
```

The MCP server is a thin translation layer. It contains zero business logic — it wraps REST API calls. This ensures all auth, logging, and rate limiting apply uniformly regardless of whether the caller is a human, an API client, or an MCP agent.

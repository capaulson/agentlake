# Deployment Guide

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Docker | 24+ | Container runtime |
| Docker Compose | v2+ | Local development orchestration |
| kubectl | 1.28+ | Kubernetes CLI (production) |
| kustomize | 5.0+ | Kubernetes manifest management |
| Python | 3.12+ | Backend development |
| Node.js | 20+ | Frontend development |

## Docker Compose (Development)

The fastest way to run AgentLake locally.

### 1. Clone and configure

```bash
git clone <repo-url> agentlake
cd agentlake
cp .env.example .env
```

Edit `.env` and set at minimum one LLM provider key:

```bash
# At least one of these is required
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-...
```

### 2. Start all services

```bash
make up
```

This starts PostgreSQL (with pgvector + AGE), Redis, MinIO, the API server, LLM gateway, distiller workers, the React UI, and the MCP server.

### 3. Run database migrations

```bash
make migrate
```

### 4. Seed development data (optional)

```bash
make seed
```

### 5. Verify

| Service | URL | Purpose |
|---------|-----|---------|
| API | http://localhost:8000/api/v1/health | REST API |
| UI | http://localhost:3000 | React frontend |
| LLM Gateway | http://localhost:8001/api/v1/llm/health | LLM proxy |
| MCP Server | http://localhost:8002 | MCP SSE endpoint |
| MinIO Console | http://localhost:9001 | Object storage UI |

### Stopping services

```bash
make down          # stop containers, keep data
make reset         # destroy volumes and rebuild from scratch
```

## Kubernetes (Production)

AgentLake ships with Kustomize manifests in `k8s/` with base configuration and overlays for dev and prod environments.

### Directory structure

```
k8s/
  base/               # Shared manifests for all environments
    kustomization.yaml
    namespace.yaml
    postgres.yaml
    redis.yaml
    minio.yaml
    api.yaml
    llm-gateway.yaml
    distiller.yaml
    ui.yaml
    mcp-server.yaml
    ingress.yaml
    network-policy.yaml
  overlays/
    dev/              # Single replicas, debug logging, lower resources
    prod/             # Multi-replica, JSON logging, production resources
```

### 1. Create secrets

Before deploying, create the required secrets. Do NOT commit real credentials to the repo.

```bash
# Create the namespace first
kubectl apply -f k8s/base/namespace.yaml

# PostgreSQL credentials
kubectl -n agentlake create secret generic postgres-secret \
  --from-literal=POSTGRES_USER=agentlake \
  --from-literal=POSTGRES_PASSWORD='<strong-password>' \
  --from-literal=POSTGRES_DB=agentlake \
  --from-literal=DATABASE_URL='postgresql+asyncpg://agentlake:<strong-password>@postgres:5432/agentlake' \
  --from-literal=DATABASE_SYNC_URL='postgresql://agentlake:<strong-password>@postgres:5432/agentlake'

# MinIO credentials
kubectl -n agentlake create secret generic minio-secret \
  --from-literal=MINIO_ROOT_USER=agentlake_minio \
  --from-literal=MINIO_ROOT_PASSWORD='<strong-password>' \
  --from-literal=MINIO_ACCESS_KEY=agentlake_minio \
  --from-literal=MINIO_SECRET_KEY='<strong-password>'

# API secrets
kubectl -n agentlake create secret generic api-secret \
  --from-literal=JWT_SECRET='<random-256-bit-key>' \
  --from-literal=API_KEY_SALT='<random-256-bit-key>' \
  --from-literal=LLM_GATEWAY_SERVICE_TOKEN='<random-token>'

# LLM Gateway secrets (API keys live ONLY here)
kubectl -n agentlake create secret generic llm-gateway-secret \
  --from-literal=ANTHROPIC_API_KEY='sk-ant-...' \
  --from-literal=OPENROUTER_API_KEY='sk-or-...' \
  --from-literal=LLM_GATEWAY_SERVICE_TOKEN='<same-token-as-above>'

# MCP server
kubectl -n agentlake create secret generic mcp-server-secret \
  --from-literal=AGENTLAKE_API_KEY='<api-key>'
```

### 2. Build and push images

```bash
# Backend (shared by api, llm-gateway, distiller, mcp-server)
docker build -t your-registry/agentlake/api:v1.0.0 --target runtime backend/
docker push your-registry/agentlake/api:v1.0.0

# Frontend
docker build -t your-registry/agentlake/ui:v1.0.0 frontend/
docker push your-registry/agentlake/ui:v1.0.0
```

Update image references in the overlays or use `kustomize edit set image`.

### 3. Deploy with dev overlay

```bash
kubectl apply -k k8s/overlays/dev
```

### 4. Deploy with prod overlay

```bash
kubectl apply -k k8s/overlays/prod
```

### 5. Run database migrations

```bash
kubectl -n agentlake exec -it deploy/api -- alembic upgrade head
```

### 6. Configure TLS

The ingress expects a TLS secret named `agentlake-tls`. Create it with cert-manager or manually:

```bash
kubectl -n agentlake create secret tls agentlake-tls \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key
```

### 7. Verify deployment

```bash
# Check all pods are running
kubectl -n agentlake get pods

# Check services
kubectl -n agentlake get svc

# Test API health
kubectl -n agentlake port-forward svc/api 8000:8000
curl http://localhost:8000/api/v1/health
```

## Environment Configuration

All configuration is via environment variables. See `.env.example` for the complete list.

### Critical production overrides

| Variable | Why |
|----------|-----|
| `JWT_SECRET` | Must be a cryptographically random 256-bit key |
| `API_KEY_SALT` | Must be a cryptographically random 256-bit key |
| `POSTGRES_PASSWORD` | Strong password, not the dev default |
| `MINIO_ROOT_PASSWORD` | Strong password, not the dev default |
| `ANTHROPIC_API_KEY` | Real provider key in LLM Gateway ONLY |
| `LLM_GATEWAY_SERVICE_TOKEN` | Shared secret between services and LLM gateway |
| `API_CORS_ORIGINS` | Set to your actual frontend domain |

### Network policies

The Kubernetes manifests include network policies that enforce:

- Only the LLM Gateway can make external HTTPS requests (to reach LLM provider APIs)
- PostgreSQL accepts connections only from api, llm-gateway, and distiller
- Redis accepts connections only from api, distiller, and llm-gateway
- MinIO accepts connections only from api and distiller

These policies require a CNI plugin that supports NetworkPolicy (Calico, Cilium, etc.).

## Database Initialization

On first deploy, the PostgreSQL init script (`scripts/init-db.sql`) creates:

1. `uuid-ossp` extension for UUID generation
2. `vector` extension (pgvector) for embedding storage and similarity search
3. `pg_trgm` extension for trigram-based text search
4. `age` extension for Apache AGE graph queries
5. The `agentlake_graph` graph instance

After extensions are loaded, run Alembic migrations to create application tables:

```bash
# Docker Compose
make migrate

# Kubernetes
kubectl -n agentlake exec -it deploy/api -- alembic upgrade head
```

## First-Time Setup Checklist

1. Configure `.env` with at least one LLM provider API key
2. Start infrastructure services (PostgreSQL, Redis, MinIO)
3. Wait for health checks to pass
4. Run database migrations
5. Create initial admin API key (via seed script or API)
6. Upload a test file to verify the full pipeline
7. Search for content from the uploaded file
8. Verify citations link back to the raw source

# Scaling Guide

## Architecture Overview

AgentLake is designed for horizontal scaling of stateless services (API, LLM Gateway, distiller workers, UI, MCP server) and vertical scaling of stateful services (PostgreSQL, Redis, MinIO).

```
                    ┌──────────────┐
                    │   Ingress    │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────▼───┐  ┌────▼───┐  ┌────▼───┐
         │ API x3 │  │ UI x3  │  │ MCP x2 │   ← horizontally scalable
         └────┬───┘  └────────┘  └────────┘
              │
    ┌─────────┼─────────┐
    │         │         │
┌───▼──┐ ┌───▼────┐ ┌──▼──────────┐
│Postgr│ │  Redis │ │LLM GW x3    │   ← gateway scales horizontally
│  SQL  │ │       │ └──────────────┘
└──────┘ └───┬────┘
             │
      ┌──────▼──────┐
      │Distiller x10│   ← worker pool scales with queue depth
      └─────────────┘
```

## Horizontal Pod Autoscaling (HPA)

### API Server

The API HPA scales based on CPU and memory utilization:

```yaml
# Base config (k8s/base/api.yaml)
minReplicas: 2    # dev overlay: 1, prod overlay: 3
maxReplicas: 8    # dev overlay: 2, prod overlay: 12
targetCPU: 80%
targetMemory: 85%
```

Scale-up is aggressive (2 pods per 60s), scale-down is conservative (1 pod per 120s, with a 5-minute stabilization window) to avoid flapping.

### Distiller Workers

The distiller HPA scales based on CPU as a proxy for work volume:

```yaml
# Base config (k8s/base/distiller.yaml)
minReplicas: 2    # dev overlay: 1, prod overlay: 3
maxReplicas: 10   # dev overlay: 3, prod overlay: 20
targetCPU: 70%
```

For queue-depth-based scaling (recommended for production), deploy a Prometheus adapter that exposes the Celery queue length as a custom metric:

```yaml
# Add to distiller HPA when Prometheus adapter is available
metrics:
  - type: External
    external:
      metric:
        name: celery_queue_length
        selector:
          matchLabels:
            queue: default
      target:
        type: AverageValue
        averageValue: "10"
```

### Manual scaling

```bash
# Scale distiller workers immediately
kubectl -n agentlake scale deploy/distiller --replicas=5

# Scale API pods
kubectl -n agentlake scale deploy/api --replicas=4
```

## Database Scaling

### PostgreSQL Connection Pooling

The default pool configuration in `config.py`:

```
DATABASE_POOL_SIZE = 20
DATABASE_MAX_OVERFLOW = 10
```

Each API pod maintains its own connection pool. With 3 API pods + 3 distiller pods, you need at least 180 connections available in PostgreSQL.

Tune `max_connections` in PostgreSQL:

```sql
ALTER SYSTEM SET max_connections = 300;
-- Requires restart
```

For large deployments, add PgBouncer as a connection pooler between application pods and PostgreSQL.

### PostgreSQL Vertical Scaling

For larger datasets, increase PostgreSQL resources:

| Dataset Size | CPU | Memory | Disk | `shared_buffers` | `work_mem` |
|-------------|-----|--------|------|------------------|------------|
| < 100K docs | 1 | 2Gi | 20Gi | 512MB | 16MB |
| 100K-500K docs | 2 | 4Gi | 100Gi | 1GB | 32MB |
| 500K-1M docs | 4 | 8Gi | 250Gi | 2GB | 64MB |
| > 1M docs | 8 | 16Gi | 500Gi+ | 4GB | 128MB |

Apply PostgreSQL tuning:

```sql
ALTER SYSTEM SET shared_buffers = '2GB';
ALTER SYSTEM SET effective_cache_size = '6GB';
ALTER SYSTEM SET work_mem = '64MB';
ALTER SYSTEM SET maintenance_work_mem = '512MB';
ALTER SYSTEM SET random_page_cost = 1.1;  -- for SSD storage
```

### Read Replicas

For read-heavy workloads (search, document listing), add PostgreSQL streaming replicas and route read queries to them. This requires:

1. A PostgreSQL replica StatefulSet
2. A read-only Service pointing to replicas
3. Application-level read/write splitting (configure a second `DATABASE_READ_URL`)

## Search Performance Tuning

### HNSW Index Parameters

The HNSW indexes on `processed_documents.embedding` and `document_chunks.embedding` control semantic search performance:

| Parameter | Default | Effect of Increase |
|-----------|---------|-------------------|
| `m` | 16 | Better recall, more memory, slower inserts |
| `ef_construction` | 64 | Better index quality, slower builds |
| `ef_search` | 40 (pgvector default) | Better recall at query time, slower searches |

Tune query-time `ef_search`:

```sql
SET hnsw.ef_search = 100;  -- higher for better recall
```

For 1M+ documents, consider:

```sql
-- Rebuild with higher quality
DROP INDEX ix_processed_documents_embedding;
CREATE INDEX ix_processed_documents_embedding ON processed_documents
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 128);
```

### Full-Text Search Tuning

The GIN index on `search_vector` (tsvector) handles keyword search. For large datasets:

```sql
-- Check index size
SELECT pg_size_pretty(pg_relation_size('ix_processed_documents_search_vector'));

-- If the index is fragmented after many updates
REINDEX INDEX ix_processed_documents_search_vector;
```

### Hybrid Search Optimization

Hybrid search (keyword + semantic) runs both queries and merges results. For best performance:

1. Keep the keyword search fast with the GIN index
2. Keep the semantic search fast with a well-tuned HNSW index
3. Use `LIMIT` pushdown to avoid scanning more than needed
4. Consider caching frequent search queries in Redis

## Queue Management

### Celery Queue Structure

| Queue | Priority | Contents |
|-------|----------|----------|
| `high` | Highest | User-initiated reprocessing |
| `default` | Normal | Standard file processing |
| `low` | Lowest | Batch operations, graph rebuilds |

### Monitoring queue depth

```bash
# Via Celery CLI
celery -A agentlake.workers.celery_app inspect active
celery -A agentlake.workers.celery_app inspect reserved

# Via Redis directly
redis-cli LLEN high
redis-cli LLEN default
redis-cli LLEN low
```

### Queue backlog management

If the queue is growing faster than workers can process:

1. **Scale workers:** `kubectl -n agentlake scale deploy/distiller --replicas=8`
2. **Increase concurrency:** Set `DISTILLER_CONCURRENCY=8` in the distiller ConfigMap
3. **Prioritize:** Move critical files to the `high` queue
4. **Rate limit uploads:** Temporarily reduce the upload rate at the ingress level

### Worker concurrency vs. replica count

Each worker pod runs `DISTILLER_CONCURRENCY` concurrent tasks. The total processing capacity is:

```
total_capacity = replicas * DISTILLER_CONCURRENCY
```

| Scenario | Replicas | Concurrency | Total Capacity |
|----------|----------|-------------|----------------|
| Dev | 1 | 2 | 2 concurrent tasks |
| Standard | 3 | 4 | 12 concurrent tasks |
| High load | 10 | 8 | 80 concurrent tasks |

Prefer more replicas with lower concurrency over fewer replicas with high concurrency. This provides better fault tolerance and smoother CPU utilization.

## Redis Scaling

Redis is used for:
- Celery task broker
- Result caching
- Rate limiting (LLM Gateway)
- SSE/WebSocket message fanout

### Memory sizing

```
Base overhead:          ~50MB
Per queued task:        ~2KB
Per cached search:      ~10KB
Rate limit state:       ~1MB
```

For most deployments, 512Mi-1Gi is sufficient. If Redis memory pressure triggers evictions, either:
- Increase the memory limit
- Reduce cache TTLs
- Move to Redis Cluster for larger deployments

## Performance Targets

From the PRD, these are the targets to maintain as you scale:

| Metric | Target | How to verify |
|--------|--------|---------------|
| Keyword search p95 | < 100ms at 1M docs | Load test with Locust |
| Semantic search p95 | < 200ms at 1M docs | Load test with Locust |
| Hybrid search p95 | < 250ms at 1M docs | Load test with Locust |
| File upload throughput | 50 files/min | Bulk upload test |
| Processing latency | < 60s per file | Monitor Celery task duration |
| API response (non-search) | < 50ms p95 | Load test |
| Concurrent connections | 500+ | Load test |

Run scale tests:

```bash
make test-scale
```

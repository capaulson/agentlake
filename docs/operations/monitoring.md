# Monitoring

## Health Endpoints

Every service exposes a health check endpoint. Use these for liveness/readiness probes and uptime monitoring.

| Service | Endpoint | Port | Expected Response |
|---------|----------|------|-------------------|
| API | `GET /api/v1/health` | 8000 | `{"status": "healthy", ...}` |
| LLM Gateway | `GET /api/v1/llm/health` | 8001 | `{"status": "healthy", ...}` |
| MCP Server | TCP check | 8002 | Connection accepted |
| UI | `GET /healthz` | 3000 | `200 OK` |
| PostgreSQL | `pg_isready` | 5432 | Exit code 0 |
| Redis | `redis-cli ping` | 6379 | `PONG` |
| MinIO | `GET /minio/health/live` | 9000 | `200 OK` |

### Quick health check script

```bash
#!/bin/bash
echo "API:         $(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/health)"
echo "LLM Gateway: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/v1/llm/health)"
echo "UI:          $(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/healthz)"
echo "MinIO:       $(curl -s -o /dev/null -w '%{http_code}' http://localhost:9000/minio/health/live)"
echo "Redis:       $(docker compose exec -T redis redis-cli ping)"
echo "PostgreSQL:  $(docker compose exec -T postgres pg_isready -U agentlake)"
```

## Key Metrics to Watch

### API Server

| Metric | Warning | Critical | How to check |
|--------|---------|----------|--------------|
| Request latency p95 | > 200ms | > 500ms | Access logs, APM |
| Error rate (5xx) | > 1% | > 5% | Access logs |
| Active connections | > 400 | > 480 | `/api/v1/health` |
| Search latency p95 | > 250ms | > 1s | Application logs |

### LLM Gateway

| Metric | Warning | Critical | How to check |
|--------|---------|----------|--------------|
| Provider error rate | > 5% | > 20% | Application logs |
| Token usage (daily) | > 80% budget | > 95% budget | Token ledger table |
| Fallback activations | > 10/hour | > 50/hour | Application logs |
| Request queue depth | > 50 | > 200 | Redis queue length |

### Distiller (Celery Workers)

| Metric | Warning | Critical | How to check |
|--------|---------|----------|--------------|
| Queue depth | > 100 | > 500 | `celery inspect active` or Redis |
| Task failure rate | > 5% | > 15% | Celery logs |
| Processing latency | > 60s/file | > 180s/file | Application logs |
| Worker count | < min replicas | 0 | `kubectl get pods` |

### PostgreSQL

| Metric | Warning | Critical | How to check |
|--------|---------|----------|--------------|
| Connection count | > 80% max | > 95% max | `pg_stat_activity` |
| Replication lag | > 1s | > 10s | `pg_stat_replication` |
| Disk usage | > 80% | > 90% | `df -h` on PVC |
| Slow queries | > 1s | > 5s | `pg_stat_statements` |
| Dead tuples | > 10% | > 25% | `pg_stat_user_tables` |

### Redis

| Metric | Warning | Critical | How to check |
|--------|---------|----------|--------------|
| Memory usage | > 80% limit | > 95% limit | `redis-cli info memory` |
| Connected clients | > 200 | > 400 | `redis-cli info clients` |
| Evicted keys | > 0 (if unexpected) | sustained | `redis-cli info stats` |

### MinIO

| Metric | Warning | Critical | How to check |
|--------|---------|----------|--------------|
| Disk usage | > 80% | > 90% | MinIO console or `mc admin info` |
| Request errors | > 1% | > 5% | MinIO access logs |

## Logging

All backend services use `structlog` with structured JSON output (in production) or console-formatted output (in development).

### Log fields

Every log entry includes:

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 timestamp |
| `level` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `service` | Service name (api, llm-gateway, distiller) |
| `request_id` | Unique request correlation ID |
| `message` | Human-readable log message |

### Viewing logs

```bash
# Docker Compose: all services
make logs

# Docker Compose: specific service
docker compose logs -f api

# Kubernetes: specific pod
kubectl -n agentlake logs -f deploy/api

# Kubernetes: all pods for a service
kubectl -n agentlake logs -l app.kubernetes.io/name=api --tail=100
```

### Log levels

Set via the `LOG_LEVEL` environment variable:

| Level | When to use |
|-------|-------------|
| `DEBUG` | Development only. Includes request/response bodies, SQL queries |
| `INFO` | Production default. Key operations, timing, status changes |
| `WARNING` | Degraded behavior (fallback provider, retry, slow query) |
| `ERROR` | Failures requiring attention (task failure, provider down) |

### Log aggregation

For production, ship logs to a centralized system:

- **Fluentd/Fluent Bit**: Deploy as a DaemonSet to collect container stdout
- **Loki + Grafana**: Lightweight log aggregation with label-based queries
- **ELK Stack**: Elasticsearch + Logstash + Kibana for full-text log search

The JSON log format is ready for ingestion by all of these systems without additional parsing.

## Alerting Recommendations

### Critical alerts (page on-call)

| Alert | Condition | Action |
|-------|-----------|--------|
| API down | Health check fails for > 2 min | Check pods, recent deploys |
| LLM Gateway down | Health check fails for > 2 min | Check pods, provider status |
| All workers down | No Celery workers responding | Check pods, Redis connectivity |
| Database unreachable | pg_isready fails for > 1 min | Check StatefulSet, PVC, disk |
| Disk > 90% | Any PVC above threshold | Expand PVC or clean old data |

### Warning alerts (notify channel)

| Alert | Condition | Action |
|-------|-----------|--------|
| High error rate | 5xx > 5% for 5 min | Check logs for root cause |
| LLM fallback active | Primary provider failing | Check provider status page |
| Queue growing | Celery queue > 200 for 10 min | Scale distiller workers |
| Slow searches | p95 > 500ms for 10 min | Check database load, index health |
| High token spend | Daily usage > 80% budget | Review task routing config |

## Database Monitoring Queries

### Active connections

```sql
SELECT count(*) as total,
       state,
       application_name
FROM pg_stat_activity
WHERE datname = 'agentlake'
GROUP BY state, application_name;
```

### Slow queries

```sql
SELECT query, mean_exec_time, calls, total_exec_time
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'agentlake')
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### Table sizes

```sql
SELECT relname as table,
       pg_size_pretty(pg_total_relation_size(relid)) as total_size,
       n_live_tup as row_count
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```

### Index health

```sql
SELECT indexrelname as index,
       idx_scan as scans,
       pg_size_pretty(pg_relation_size(indexrelid)) as size
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan ASC;
```

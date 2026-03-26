# Backup and Recovery

## Overview

AgentLake has two stateful components that require backup:

1. **PostgreSQL** -- all metadata, processed documents, embeddings, entity graph, diff logs
2. **MinIO** -- raw uploaded files (the vault)

Redis is used as a cache and Celery broker; it does not require backup.

## Automated Backup Script

The project includes `scripts/backup.sh` which creates timestamped archives containing both a PostgreSQL dump and a MinIO data snapshot.

### Usage

```bash
# Default: writes to ./backups/
./scripts/backup.sh

# Custom destination
BACKUP_DIR=/mnt/nfs/backups ./scripts/backup.sh
```

### What it produces

```
backups/
  agentlake_backup_20260324_083000.tar.gz
    ├── database.dump      # pg_dump custom format, compressed
    ├── minio_data/        # full MinIO data directory
    └── pg_dump.log        # dump log for diagnostics
```

### Retention

By default, the script retains the 7 most recent backups. Override with:

```bash
BACKUP_RETAIN=14 ./scripts/backup.sh
```

## PostgreSQL Backup

### Manual pg_dump

```bash
# Docker Compose
docker compose exec -T postgres \
  pg_dump -U agentlake -d agentlake \
    --format=custom \
    --compress=6 \
    > backup_$(date +%Y%m%d).dump

# Kubernetes
kubectl -n agentlake exec -i postgres-0 -- \
  pg_dump -U agentlake -d agentlake \
    --format=custom \
    --compress=6 \
    > backup_$(date +%Y%m%d).dump
```

### What is included

- All tables (files, processed_documents, document_chunks, citations, diff_logs, api_keys, tags)
- All indexes (B-tree, GIN for full-text search, HNSW for vector similarity)
- Extensions data (pgvector embeddings, Apache AGE graph)
- Sequences and constraints

### Backup with specific tables

```bash
# Backup only documents and chunks (e.g., for migration)
pg_dump -U agentlake -d agentlake \
  --format=custom \
  -t processed_documents \
  -t document_chunks \
  -t citations \
  > documents_backup.dump
```

## MinIO Backup

### Using mc (MinIO Client)

```bash
# Configure mc alias
mc alias set agentlake http://localhost:9000 agentlake_minio agentlake_minio_secret

# Mirror the bucket to a local directory
mc mirror agentlake/agentlake-vault ./backup_vault/

# Mirror to another S3-compatible target
mc mirror agentlake/agentlake-vault s3/backup-bucket/agentlake-vault/
```

### Using Docker cp (development)

```bash
docker cp agentlake-minio:/data ./minio_backup/
```

### Kubernetes

```bash
# Port-forward MinIO and use mc
kubectl -n agentlake port-forward svc/minio 9000:9000 &
mc alias set agentlake-k8s http://localhost:9000 <access-key> <secret-key>
mc mirror agentlake-k8s/agentlake-vault ./backup_vault/
```

## Restore Procedures

### PostgreSQL Restore

```bash
# Docker Compose
docker compose exec -T postgres \
  pg_restore -U agentlake -d agentlake \
    --clean \
    --if-exists \
    --no-owner \
    < backup_20260324.dump

# Kubernetes
kubectl -n agentlake exec -i postgres-0 -- \
  pg_restore -U agentlake -d agentlake \
    --clean \
    --if-exists \
    --no-owner \
    < backup_20260324.dump
```

**Important:** After restoring, verify that extensions are loaded:

```sql
SELECT extname FROM pg_extension;
-- Should include: uuid-ossp, vector, pg_trgm, age
```

If the AGE graph is missing, re-run the init script:

```bash
# Docker Compose
docker compose exec -T postgres psql -U agentlake -d agentlake \
  < scripts/init-db.sql
```

### MinIO Restore

```bash
# Using mc
mc mirror ./backup_vault/ agentlake/agentlake-vault/

# Using Docker cp (development)
docker cp ./minio_backup/data agentlake-minio:/
docker compose restart minio
```

### Full System Restore

1. Stop all application services (api, distiller, llm-gateway, ui, mcp-server)
2. Restore PostgreSQL from dump
3. Verify extensions and re-run init-db.sql if needed
4. Run any pending Alembic migrations: `alembic upgrade head`
5. Restore MinIO data
6. Restart all services
7. Verify health endpoints respond
8. Run a test search to confirm indexes are intact

## Scheduled Backups

### Cron (Linux/macOS)

```bash
# Daily at 2 AM, retain 14 backups
0 2 * * * BACKUP_DIR=/mnt/backups/agentlake BACKUP_RETAIN=14 /path/to/agentlake/scripts/backup.sh >> /var/log/agentlake-backup.log 2>&1
```

### Kubernetes CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: agentlake-backup
  namespace: agentlake
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: postgres:16
              command:
                - /bin/bash
                - -c
                - |
                  pg_dump -h postgres -U agentlake -d agentlake \
                    --format=custom --compress=6 \
                    > /backups/agentlake_$(date +%Y%m%d_%H%M%S).dump
              envFrom:
                - secretRef:
                    name: postgres-secret
              volumeMounts:
                - name: backup-volume
                  mountPath: /backups
          restartPolicy: OnFailure
          volumes:
            - name: backup-volume
              persistentVolumeClaim:
                claimName: backup-pvc
```

## Disaster Recovery

### Recovery Time Objectives

| Scenario | RTO | RPO |
|----------|-----|-----|
| Single pod failure | < 1 min (K8s restarts) | 0 (stateless) |
| Database corruption | < 30 min | Last backup |
| Full cluster loss | < 2 hours | Last backup |
| MinIO data loss | < 1 hour | Last backup |

### Recovery Priority Order

1. PostgreSQL (all metadata, document content, embeddings)
2. MinIO (raw source files)
3. Redis (ephemeral; restarts empty)
4. Application services (stateless; just redeploy)

### Rebuilding Derived Data

If the entity graph is lost or corrupted, it can be rebuilt from document entities:

```bash
# Trigger a graph rebuild via the API
curl -X POST http://localhost:8000/api/v1/admin/rebuild-graph \
  -H "Authorization: Bearer <admin-token>"
```

Search indexes (HNSW, GIN) are part of the PostgreSQL dump and restored automatically. If they need rebuilding:

```sql
REINDEX INDEX ix_processed_documents_embedding;
REINDEX INDEX ix_processed_documents_search_vector;
REINDEX INDEX ix_document_chunks_embedding;
```

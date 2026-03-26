#!/usr/bin/env bash
# =============================================================================
# AgentLake — Backup Script
#
# Creates a timestamped archive containing:
#   1. PostgreSQL database dump (pg_dump)
#   2. MinIO object storage data snapshot
#
# Usage:
#   ./scripts/backup.sh                      # backup to ./backups/
#   BACKUP_DIR=/mnt/nfs/backups ./scripts/backup.sh  # custom destination
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via environment)
# ---------------------------------------------------------------------------
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_DIR:-./backups}"
WORK_DIR="${BACKUP_DIR}/.work_${TIMESTAMP}"
ARCHIVE_NAME="agentlake_backup_${TIMESTAMP}.tar.gz"

COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-ftknox}"

# Docker Compose service names
PG_SERVICE="${PG_SERVICE:-postgres}"
MINIO_SERVICE="${MINIO_SERVICE:-minio}"

# PostgreSQL connection (used inside the container)
PG_USER="${PG_USER:-agentlake}"
PG_DB="${PG_DB:-agentlake}"

# MinIO bucket path inside the container
MINIO_DATA_PATH="${MINIO_DATA_PATH:-/data}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $(date +%H:%M:%S) $*"; }
error() { echo "[ERROR] $(date +%H:%M:%S) $*" >&2; }

cleanup() {
    info "Cleaning up temporary files..."
    rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    error "docker is not installed or not in PATH."
    exit 1
fi

mkdir -p "${BACKUP_DIR}" "${WORK_DIR}"

# ---------------------------------------------------------------------------
# 1. PostgreSQL dump
# ---------------------------------------------------------------------------
info "Dumping PostgreSQL database '${PG_DB}'..."
docker compose exec -T "${PG_SERVICE}" \
    pg_dump -U "${PG_USER}" -d "${PG_DB}" \
        --format=custom \
        --compress=6 \
        --verbose \
    > "${WORK_DIR}/database.dump" 2>"${WORK_DIR}/pg_dump.log"

PG_DUMP_SIZE=$(wc -c < "${WORK_DIR}/database.dump" | tr -d ' ')
info "Database dump complete (${PG_DUMP_SIZE} bytes)."

# ---------------------------------------------------------------------------
# 2. MinIO data snapshot
# ---------------------------------------------------------------------------
info "Copying MinIO data from container..."
MINIO_CONTAINER=$(docker compose ps -q "${MINIO_SERVICE}" 2>/dev/null || true)

if [ -n "${MINIO_CONTAINER}" ]; then
    docker cp "${MINIO_CONTAINER}:${MINIO_DATA_PATH}" "${WORK_DIR}/minio_data"
    info "MinIO data copied."
else
    info "MinIO container not running — skipping object storage backup."
    mkdir -p "${WORK_DIR}/minio_data"
fi

# ---------------------------------------------------------------------------
# 3. Package into timestamped archive
# ---------------------------------------------------------------------------
info "Creating archive ${ARCHIVE_NAME}..."
tar -czf "${BACKUP_DIR}/${ARCHIVE_NAME}" \
    -C "${WORK_DIR}" \
    database.dump \
    minio_data \
    pg_dump.log

ARCHIVE_SIZE=$(wc -c < "${BACKUP_DIR}/${ARCHIVE_NAME}" | tr -d ' ')
info "Backup complete: ${BACKUP_DIR}/${ARCHIVE_NAME} (${ARCHIVE_SIZE} bytes)"

# ---------------------------------------------------------------------------
# 4. Retention — keep last 7 backups by default
# ---------------------------------------------------------------------------
RETAIN="${BACKUP_RETAIN:-7}"
BACKUP_COUNT=$(find "${BACKUP_DIR}" -maxdepth 1 -name 'agentlake_backup_*.tar.gz' | wc -l | tr -d ' ')

if [ "${BACKUP_COUNT}" -gt "${RETAIN}" ]; then
    REMOVE_COUNT=$((BACKUP_COUNT - RETAIN))
    info "Pruning ${REMOVE_COUNT} old backup(s) (retaining ${RETAIN})..."
    find "${BACKUP_DIR}" -maxdepth 1 -name 'agentlake_backup_*.tar.gz' -print0 | \
        sort -z | \
        head -z -n "${REMOVE_COUNT}" | \
        xargs -0 rm -f
fi

info "Done."

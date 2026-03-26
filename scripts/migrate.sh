#!/usr/bin/env bash
# =============================================================================
# AgentLake — Run Alembic Migrations Inside the API Container
#
# Usage:
#   ./scripts/migrate.sh              # upgrade to head
#   ./scripts/migrate.sh head         # upgrade to head (explicit)
#   ./scripts/migrate.sh downgrade -1 # downgrade one revision
#   ./scripts/migrate.sh history      # show migration history
#   ./scripts/migrate.sh current      # show current revision
# =============================================================================

set -euo pipefail

API_SERVICE="${API_SERVICE:-api}"
ALEMBIC_CMD="${1:-upgrade}"
ALEMBIC_ARG="${2:-head}"

info()  { echo "[INFO]  $(date +%H:%M:%S) $*"; }
error() { echo "[ERROR] $(date +%H:%M:%S) $*" >&2; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    error "docker is not installed or not in PATH."
    exit 1
fi

API_CONTAINER=$(docker compose ps -q "${API_SERVICE}" 2>/dev/null || true)

if [ -z "${API_CONTAINER}" ]; then
    error "API container is not running. Start it with 'make up' first."
    exit 1
fi

# ---------------------------------------------------------------------------
# Run migration
# ---------------------------------------------------------------------------
case "${ALEMBIC_CMD}" in
    upgrade|downgrade)
        info "Running: alembic ${ALEMBIC_CMD} ${ALEMBIC_ARG}"
        docker compose exec "${API_SERVICE}" \
            alembic "${ALEMBIC_CMD}" "${ALEMBIC_ARG}"
        ;;
    history|current|heads|branches|show)
        info "Running: alembic ${ALEMBIC_CMD}"
        docker compose exec "${API_SERVICE}" \
            alembic "${ALEMBIC_CMD}"
        ;;
    *)
        error "Unknown alembic command: ${ALEMBIC_CMD}"
        echo "Usage: $0 [upgrade|downgrade|history|current|heads|branches|show] [revision]"
        exit 1
        ;;
esac

info "Migration complete."

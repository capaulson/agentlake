# =============================================================================
# AgentLake Backend — Multi-stage Docker Build
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install Python dependencies and prepare source
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build toolchain needed by some Python C-extension wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

# Install dependencies into the system site-packages so they can be copied to
# the runtime image.  We try uv first (fast), fall back to pip.
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache "." || \
    pip install --no-cache-dir "."

COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/

# ---------------------------------------------------------------------------
# Stage 2: Runtime — minimal image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# libpq is needed at runtime for psycopg2 / asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r agentlake && useradd -r -g agentlake -s /usr/sbin/nologin agentlake

WORKDIR /app

# Copy installed packages and executables from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source, alembic config, and migrations
COPY --from=builder /app/src /app/src
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/alembic /app/alembic

# Make sure the package is importable
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

USER agentlake

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "agentlake.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# =============================================================================
# AgentLake PostgreSQL — pgvector + Apache AGE extensions
# =============================================================================
FROM postgres:16 AS builder

# Install build dependencies + ca-certificates for git
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        postgresql-server-dev-16 \
        libreadline-dev \
        zlib1g-dev \
        flex \
        bison \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Install pgvector (available as a Debian package)
# ---------------------------------------------------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-16-pgvector && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Build Apache AGE from source (PG16 branch)
# ---------------------------------------------------------------------------
RUN git clone --branch release/PG16/1.5.0 --depth 1 \
        https://github.com/apache/age.git /tmp/age && \
    cd /tmp/age && \
    make -j"$(nproc)" && \
    make install && \
    rm -rf /tmp/age

# ---------------------------------------------------------------------------
# Final image — slim runtime with extensions installed
# ---------------------------------------------------------------------------
FROM postgres:16

# Copy pgvector extension files from builder
COPY --from=builder /usr/share/postgresql/16/extension/vector* /usr/share/postgresql/16/extension/
COPY --from=builder /usr/lib/postgresql/16/lib/vector.so /usr/lib/postgresql/16/lib/

# Copy Apache AGE extension files from builder
COPY --from=builder /usr/share/postgresql/16/extension/age* /usr/share/postgresql/16/extension/
COPY --from=builder /usr/lib/postgresql/16/lib/age.so /usr/lib/postgresql/16/lib/

# Preload AGE shared library so it is available for CREATE EXTENSION
RUN echo "shared_preload_libraries = 'age'" >> /usr/share/postgresql/postgresql.conf.sample

EXPOSE 5432

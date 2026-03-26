-- =============================================================================
-- AgentLake — Database Initialisation
-- Executed automatically by the PostgreSQL entrypoint on first container start.
-- =============================================================================

-- Core UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Vector similarity search (pgvector)
CREATE EXTENSION IF NOT EXISTS "vector";

-- Trigram index for fast LIKE / ILIKE queries
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Apache AGE graph extension
CREATE EXTENSION IF NOT EXISTS "age";
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create the application graph (idempotent — AGE errors if graph already exists)
DO $$
BEGIN
    PERFORM create_graph('agentlake_graph');
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Graph agentlake_graph already exists, skipping creation.';
END;
$$;

-- Reset search_path to default
SET search_path = "$user", public;

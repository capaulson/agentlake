# Feature Spec: Entity Relationship Graph

## Overview

AgentLake maintains a graph of relationships between extracted entities. When the processing pipeline extracts entities (people, organizations, products, technologies, etc.) from documents, it also identifies and stores the relationships between them. This enables queries like "show me everything connected to Siemens within 2 hops" or "what products does this person work on?"

The graph is implemented using **Apache AGE** — a PostgreSQL extension that adds graph database capabilities (openCypher query language) directly inside our existing PostgreSQL instance. This avoids adding a separate Neo4j deployment while getting full graph query power.

---

## Why Apache AGE (Not Neo4j)

| Factor | Apache AGE | Neo4j |
|--------|-----------|-------|
| Infrastructure | Same PostgreSQL instance | Separate server + ops |
| Backup | Same pg_dump | Separate backup pipeline |
| Joins with relational data | Native (same DB) | Cross-system queries |
| Query language | openCypher (same as Neo4j) | openCypher / Cypher |
| Maturity | Production-ready, AGPL | Mature, commercial license |
| Cost | Free (PostgreSQL extension) | Enterprise license $$ |

The decisive advantage: graph data and relational data live in the same database, so we can join graph traversals with full-text search, vector search, and tag queries in a single transaction.

---

## Graph Schema

### Vertices (Nodes)

```cypher
-- Entity node: represents a named entity extracted from documents
(:Entity {
    id: "uuid",
    name: "Siemens",
    type: "organization",        -- person, organization, product, technology, location, event
    canonical_name: "siemens",   -- lowercase normalized for dedup
    first_seen_at: "2026-03-01T...",
    document_count: 47,          -- how many documents mention this entity
    properties: {}               -- extensible JSONB
})
```

### Edges (Relationships)

```cypher
-- Relationship between entities, extracted from document context
[:RELATED_TO {
    id: "uuid",
    relationship_type: "partners_with",  -- see relationship types below
    description: "Siemens and NVIDIA collaborate on digital twin factory simulation",
    confidence: 0.89,
    source_document_id: "uuid",
    source_citation_index: 3,
    extracted_at: "2026-03-24T...",
    weight: 1.0                          -- incremented when same relationship found in multiple docs
}]

-- Document-to-Entity edge (which documents mention which entities)
[:MENTIONED_IN {
    document_id: "uuid",
    mention_count: 5,                    -- how many times in this document
    context_snippet: "first mention context..."
}]
```

### Relationship Types

| Type | Description | Example |
|------|-------------|---------|
| `partners_with` | Business partnership | Siemens ↔ NVIDIA |
| `works_at` | Person employed by org | Chris → NVIDIA |
| `develops` | Org/person develops product | NVIDIA → Isaac Sim |
| `uses` | Entity uses technology/product | Siemens → Omniverse |
| `competes_with` | Competitive relationship | Physical Intelligence ↔ NVIDIA |
| `part_of` | Hierarchical containment | Isaac Sim → Omniverse |
| `located_in` | Geographic relationship | NVIDIA → Santa Clara |
| `funded_by` | Investment relationship | 1X → OpenAI |
| `successor_of` | Temporal succession | GR00T N1.6 → GR00T N1 |
| `related_to` | Generic relationship | Catch-all |

The LLM assigns relationship types during entity extraction (Layer 2, Stage 5).

---

## PostgreSQL Setup

### Extension Installation

```sql
-- Apache AGE extension (installed in Dockerfile or init script)
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create the graph
SELECT create_graph('agentlake_graph');
```

### Integration with Existing Schema

The `entities` JSONB column on `processed_documents` continues to serve as the source of truth for per-document entity lists. The graph is a **derived index** built from those entity lists plus LLM-extracted relationships.

```
ProcessedDocument.entities (JSONB) ──→ Graph vertices + MENTIONED_IN edges
LLM relationship extraction         ──→ Graph relationship edges
```

If the graph is corrupted or lost, it can be fully rebuilt from the document entities.

---

## Graph Population Pipeline

During Layer 2 processing (after entity extraction):

```
Stage 5a: Extract entities (existing) ──→ entity list
Stage 5b: Extract relationships (NEW) ──→ relationship list
Stage 5c: Upsert to graph (NEW)       ──→ Apache AGE vertices + edges
```

### Relationship Extraction Prompt

Added to the processing pipeline after entity extraction:

```
Given these entities extracted from the document:
{entity_list}

And this document text:
{document_text}

Identify relationships between the entities. For each relationship, provide:
- source_entity: name of the first entity
- target_entity: name of the second entity
- relationship_type: one of [partners_with, works_at, develops, uses, competes_with, part_of, located_in, funded_by, successor_of, related_to]
- description: one-sentence description of the relationship
- confidence: 0.0 to 1.0

Respond with ONLY valid YAML.
```

### Entity Deduplication

Entities are deduplicated by `canonical_name` (lowercase, stripped of common suffixes like "Inc.", "Corp.", "LLC"):

```python
def canonicalize(name: str) -> str:
    name = name.lower().strip()
    for suffix in [" inc", " inc.", " corp", " corp.", " llc", " ltd", " ltd.", " co.", " gmbh"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name
```

When a new entity is extracted:
1. Compute `canonical_name`
2. Check if a vertex with that `canonical_name` already exists
3. If yes → increment `document_count`, add `MENTIONED_IN` edge
4. If no → create new vertex + edge

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/graph/entity/{entity_id}` | Get entity with all relationships |
| GET | `/api/v1/graph/entity/{entity_id}/neighbors?depth=2` | Traverse N hops |
| GET | `/api/v1/graph/search?q=siemens&type=organization` | Search entities |
| GET | `/api/v1/graph/path?from={id}&to={id}` | Shortest path between entities |
| GET | `/api/v1/graph/relationships?type=partners_with` | List relationships by type |
| GET | `/api/v1/graph/stats` | Graph statistics (node count, edge count, etc.) |
| GET | `/api/v1/graph/entity/{entity_id}/documents` | Documents mentioning this entity |

### Example: Neighbor Traversal

```
GET /api/v1/graph/entity/{nvidia_id}/neighbors?depth=2&relationship_types=partners_with,develops
```

```json
{
  "center": {"id": "...", "name": "NVIDIA", "type": "organization"},
  "nodes": [
    {"id": "...", "name": "Siemens", "type": "organization", "depth": 1},
    {"id": "...", "name": "Isaac Sim", "type": "product", "depth": 1},
    {"id": "...", "name": "Omniverse", "type": "product", "depth": 1},
    {"id": "...", "name": "F80 Factory", "type": "location", "depth": 2}
  ],
  "edges": [
    {"source": "NVIDIA", "target": "Siemens", "type": "partners_with", "weight": 12},
    {"source": "NVIDIA", "target": "Isaac Sim", "type": "develops", "weight": 34},
    {"source": "Siemens", "target": "F80 Factory", "type": "located_in", "weight": 5}
  ]
}
```

### Cypher Queries (Internal)

```cypher
-- Find all entities connected to NVIDIA within 2 hops
SELECT * FROM cypher('agentlake_graph', $$
    MATCH (n:Entity {canonical_name: 'nvidia'})-[r*1..2]-(m:Entity)
    RETURN n, r, m
$$) AS (n agtype, r agtype, m agtype);

-- Shortest path between two entities
SELECT * FROM cypher('agentlake_graph', $$
    MATCH p = shortestPath(
        (a:Entity {canonical_name: 'nvidia'})-[*]-(b:Entity {canonical_name: 'siemens'})
    )
    RETURN p
$$) AS (p agtype);
```

---

## React UI: Graph Visualization

A new page in the React UI: `/graph`

- **Interactive force-directed graph** using D3.js or react-force-graph
- Click an entity node → expands its neighbors
- Edge thickness represents relationship weight (more documents → thicker)
- Color-coded by entity type (org=blue, person=green, product=teal, etc.)
- Filter sidebar: filter by entity type, relationship type, min weight
- Click a relationship edge → shows the source document and citation
- Keyboard shortcut: `Cmd+G` to navigate to graph view

---

## Testing Requirements

- **Unit:** Entity canonicalization logic
- **Unit:** Relationship type classification
- **Integration:** Upload document → verify entities appear as graph vertices
- **Integration:** Upload two related documents → verify relationships detected and weighted
- **Integration:** Graph traversal API returns correct neighbors at depth 1 and 2
- **Integration:** Shortest path between known connected entities
- **Integration:** Entity deduplication (same entity mentioned in different docs → one vertex)
- **Scale:** 100K entities, 500K relationships → traversal under 200ms

---

## Infrastructure

- Apache AGE is installed as a PostgreSQL extension in the same container
- Dockerfile: `RUN apt-get install -y postgresql-16-age`
- No additional containers or services needed
- Graph data is backed up with the same pg_dump as all other PostgreSQL data

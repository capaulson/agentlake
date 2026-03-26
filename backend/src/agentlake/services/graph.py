"""Entity graph service using Apache AGE (PostgreSQL graph extension).

Manages the entity relationship graph that is derived from processed
documents.  Entities and relationships are stored as vertices and edges
in an Apache AGE graph, enabling Cypher queries for traversal, shortest
path, and neighborhood exploration.

The graph is a derived index that can be rebuilt entirely from the
``entities`` and ``relationships`` fields in processed documents.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.models.document import ProcessedDocument

logger = structlog.get_logger(__name__)

# Regex for stripping common corporate suffixes
_SUFFIX_PATTERN = re.compile(
    r"\s*,?\s*\b(Inc|Corp|Corporation|LLC|Ltd|Limited|GmbH|Co|Company|PLC|LP|LLP|AG|SA|NV|BV)\b\.?\s*$",
    re.IGNORECASE,
)
_LEADING_THE = re.compile(r"^The\s+", re.IGNORECASE)
_TRAILING_PUNCT = re.compile(r"[.,;:!?]+$")
_MULTI_SPACE = re.compile(r"\s+")


class GraphService:
    """Service for managing the Apache AGE entity relationship graph.

    Args:
        db: Async SQLAlchemy session.
        graph_name: Name of the AGE graph (default: agentlake_graph).
    """

    def __init__(
        self,
        db: AsyncSession,
        graph_name: str = "agentlake_graph",
    ) -> None:
        self.db = db
        self.graph_name = graph_name
        self._age_available: bool | None = None

    # ── Canonicalization ──────────────────────────────────────────────────

    @staticmethod
    def canonicalize(name: str) -> str:
        """Canonicalize an entity name for deduplication.

        Applies the following transformations:
        - Lowercase
        - Strip common corporate suffixes (Inc., Corp., LLC, etc.)
        - Strip leading "The "
        - Strip trailing punctuation
        - Normalize whitespace

        Args:
            name: Raw entity name.

        Returns:
            Canonicalized entity name.
        """
        result = name.strip()
        result = _LEADING_THE.sub("", result)
        result = _SUFFIX_PATTERN.sub("", result)
        result = _TRAILING_PUNCT.sub("", result)
        result = _MULTI_SPACE.sub(" ", result)
        result = result.strip().lower()
        return result

    # ── AGE Cypher Execution ──────────────────────────────────────────────

    async def _check_age_available(self) -> bool:
        """Check whether Apache AGE extension is available.

        Returns:
            True if AGE is installed and the graph exists.
        """
        if self._age_available is not None:
            return self._age_available

        try:
            result = await self.db.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'age'")
            )
            row = result.scalar_one_or_none()
            if row is None:
                logger.warning("apache_age_not_installed")
                self._age_available = False
                return False

            # Ensure the graph exists
            await self.db.execute(
                text("LOAD 'age'")
            )
            await self.db.execute(
                text("SET search_path = ag_catalog, \"$user\", public")
            )
            await self.db.execute(
                text(
                    f"SELECT create_graph('{self.graph_name}') "
                    f"WHERE NOT EXISTS ("
                    f"  SELECT 1 FROM ag_catalog.ag_graph WHERE name = '{self.graph_name}'"
                    f")"
                )
            )
            self._age_available = True
            return True
        except Exception:
            logger.warning(
                "apache_age_check_failed",
                exc_info=True,
            )
            self._age_available = False
            return False

    async def _cypher(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query via Apache AGE.

        Sets the search path, executes the query wrapped in the AGE
        ``cypher()`` function, and parses the agtype results.

        Args:
            query: Cypher query string (without the SQL wrapper).
            params: Optional query parameters (embedded via string
                formatting since AGE does not support parameterized Cypher
                in all cases).

        Returns:
            List of result dicts parsed from agtype JSON.
        """
        if not await self._check_age_available():
            return []

        try:
            # Set the search path for AGE
            await self.db.execute(
                text("SET search_path = ag_catalog, \"$user\", public")
            )

            # AGE Cypher queries are wrapped in SQL
            sql = (
                f"SELECT * FROM cypher('{self.graph_name}', $$ "
                f"{query} "
                f"$$) AS (result agtype)"
            )

            result = await self.db.execute(text(sql))
            rows = result.fetchall()

            parsed: list[dict[str, Any]] = []
            for row in rows:
                raw = row[0]
                if raw is None:
                    continue
                # agtype values may be JSON strings or already parsed
                if isinstance(raw, str):
                    try:
                        parsed.append(json.loads(raw))
                    except json.JSONDecodeError:
                        parsed.append({"value": raw})
                elif isinstance(raw, dict):
                    parsed.append(raw)
                else:
                    parsed.append({"value": str(raw)})

            return parsed

        except Exception:
            logger.error(
                "cypher_query_failed",
                query=query[:200],
                exc_info=True,
            )
            return []

    # ── Entity Operations ─────────────────────────────────────────────────

    async def upsert_entity(
        self,
        name: str,
        entity_type: str,
        document_id: uuid.UUID,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Create or update an entity vertex and link it to a document.

        Args:
            name: Entity display name.
            entity_type: Entity type (ORG, PERSON, LOCATION, etc.).
            document_id: Document where this entity was found.
            properties: Optional additional properties.

        Returns:
            Entity vertex ID as a string.
        """
        canonical = self.canonicalize(name)
        props = properties or {}

        # Escape single quotes in strings for Cypher
        safe_name = name.replace("'", "\\'")
        safe_canonical = canonical.replace("'", "\\'")
        safe_type = entity_type.replace("'", "\\'")
        doc_id_str = str(document_id)

        # MERGE the entity vertex
        merge_query = (
            f"MERGE (e:Entity {{canonical_name: '{safe_canonical}'}}) "
            f"ON CREATE SET e.name = '{safe_name}', "
            f"  e.entity_type = '{safe_type}', "
            f"  e.document_count = 1, "
            f"  e.first_seen_at = timestamp() "
            f"ON MATCH SET e.document_count = e.document_count + 1 "
            f"RETURN id(e)"
        )
        results = await self._cypher(merge_query)

        entity_id = ""
        if results:
            entity_id = str(results[0].get("value", results[0].get("id", "")))

        # Create MENTIONED_IN edge to document vertex
        await self._cypher(
            f"MERGE (d:Document {{doc_id: '{doc_id_str}'}}) "
            f"ON CREATE SET d.doc_id = '{doc_id_str}'"
        )
        await self._cypher(
            f"MATCH (e:Entity {{canonical_name: '{safe_canonical}'}}), "
            f"      (d:Document {{doc_id: '{doc_id_str}'}}) "
            f"MERGE (e)-[:MENTIONED_IN]->(d)"
        )

        logger.debug(
            "entity_upserted",
            name=name,
            canonical=canonical,
            entity_type=entity_type,
            document_id=doc_id_str,
        )

        return entity_id

    async def add_relationship(
        self,
        source_name: str,
        target_name: str,
        relationship_type: str,
        description: str,
        confidence: float,
        document_id: uuid.UUID,
    ) -> None:
        """Create or update a relationship edge between two entities.

        If the edge already exists, increments its weight.

        Args:
            source_name: Source entity name.
            target_name: Target entity name.
            relationship_type: Type of relationship (e.g., "WORKS_FOR").
            description: Human-readable description of the relationship.
            confidence: Confidence score (0.0 to 1.0).
            document_id: Document where this relationship was found.
        """
        source_canonical = self.canonicalize(source_name).replace("'", "\\'")
        target_canonical = self.canonicalize(target_name).replace("'", "\\'")
        safe_rel_type = re.sub(r"[^A-Za-z0-9_]", "_", relationship_type).upper()
        safe_desc = description.replace("'", "\\'")
        doc_id_str = str(document_id)

        query = (
            f"MATCH (s:Entity {{canonical_name: '{source_canonical}'}}), "
            f"      (t:Entity {{canonical_name: '{target_canonical}'}}) "
            f"MERGE (s)-[r:{safe_rel_type}]->(t) "
            f"ON CREATE SET r.description = '{safe_desc}', "
            f"  r.confidence = {confidence}, "
            f"  r.weight = 1, "
            f"  r.source_document_id = '{doc_id_str}' "
            f"ON MATCH SET r.weight = r.weight + 1"
        )
        await self._cypher(query)

        logger.debug(
            "relationship_added",
            source=source_name,
            target=target_name,
            relationship_type=safe_rel_type,
        )

    # ── Batch Operations ──────────────────────────────────────────────────

    async def upsert_entities_and_relationships(
        self,
        document_id: uuid.UUID,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> None:
        """Batch upsert entities and relationships from the processing pipeline.

        Args:
            document_id: Document being processed.
            entities: List of entity dicts with "name" and "type" keys.
            relationships: List of relationship dicts with "source_entity",
                "target_entity", "relationship_type", and optionally
                "description" and "confidence" keys.
        """
        if not await self._check_age_available():
            logger.warning(
                "graph_upsert_skipped_age_unavailable",
                document_id=str(document_id),
                entity_count=len(entities),
            )
            return

        for entity in entities:
            name = entity.get("name", "")
            entity_type = entity.get("type", "UNKNOWN")
            if not name:
                continue
            await self.upsert_entity(
                name=name,
                entity_type=entity_type,
                document_id=document_id,
                properties=entity.get("properties"),
            )

        for rel in relationships:
            source = rel.get("source_entity", "")
            target = rel.get("target_entity", "")
            if not source or not target:
                continue
            await self.add_relationship(
                source_name=source,
                target_name=target,
                relationship_type=rel.get("relationship_type", "RELATED_TO"),
                description=rel.get("description", ""),
                confidence=rel.get("confidence", 0.5),
                document_id=document_id,
            )

        logger.info(
            "graph_entities_and_relationships_upserted",
            document_id=str(document_id),
            entity_count=len(entities),
            relationship_count=len(relationships),
        )

    # ── Search & Query ────────────────────────────────────────────────────

    async def search_entities(
        self,
        query: str,
        entity_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search entities by name prefix or substring.

        Args:
            query: Search string to match against entity names.
            entity_type: Optional filter by entity type.
            limit: Maximum number of results.

        Returns:
            List of entity dicts sorted by document_count descending.
        """
        safe_query = query.lower().replace("'", "\\'")

        type_filter = ""
        if entity_type:
            safe_type = entity_type.replace("'", "\\'")
            type_filter = f" AND e.entity_type = '{safe_type}'"

        cypher = (
            f"MATCH (e:Entity) "
            f"WHERE e.canonical_name CONTAINS '{safe_query}'{type_filter} "
            f"RETURN e "
            f"ORDER BY e.document_count DESC "
            f"LIMIT {limit}"
        )
        results = await self._cypher(cypher)

        return [self._parse_entity(r) for r in results if r]

    async def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        """Get an entity with all its relationships.

        Args:
            entity_id: The AGE vertex ID.

        Returns:
            Entity dict with a "relationships" list, or None if not found.
        """
        # Get the entity vertex
        entity_results = await self._cypher(
            f"MATCH (e:Entity) WHERE id(e) = {entity_id} RETURN e"
        )
        if not entity_results:
            return None

        entity = self._parse_entity(entity_results[0])

        # Get relationships
        rel_results = await self._cypher(
            f"MATCH (e:Entity)-[r]-(other:Entity) "
            f"WHERE id(e) = {entity_id} "
            f"RETURN e, r, other"
        )

        relationships = []
        for row in rel_results:
            rel_data = self._parse_relationship(row)
            if rel_data:
                relationships.append(rel_data)

        entity["relationships"] = relationships
        return entity

    async def get_entity_neighbors(
        self,
        entity_id: str,
        depth: int = 1,
        relationship_type: str | None = None,
        min_weight: int = 1,
    ) -> dict[str, Any]:
        """Get an entity's neighborhood up to N hops.

        Args:
            entity_id: The AGE vertex ID of the starting entity.
            depth: Maximum traversal depth (1-5).
            relationship_type: Optional filter for specific relationship types.
            min_weight: Minimum edge weight to include.

        Returns:
            Dict with entity, neighbors list, relationships list, and depth.
        """
        depth = min(depth, 5)  # Enforce max depth

        rel_filter = ""
        if relationship_type:
            safe_type = re.sub(r"[^A-Za-z0-9_]", "_", relationship_type).upper()
            rel_filter = f":{safe_type}"

        cypher = (
            f"MATCH path = (start:Entity)-[{rel_filter}*1..{depth}]-(end:Entity) "
            f"WHERE id(start) = {entity_id} "
            f"RETURN start, end, relationships(path)"
        )
        results = await self._cypher(cypher)

        # Get the starting entity
        start_results = await self._cypher(
            f"MATCH (e:Entity) WHERE id(e) = {entity_id} RETURN e"
        )
        start_entity = self._parse_entity(start_results[0]) if start_results else {}

        neighbors: dict[str, dict[str, Any]] = {}
        relationships: list[dict[str, Any]] = []

        for row in results:
            if isinstance(row, dict):
                end_data = row.get("end", row)
                end_entity = self._parse_entity({"value": end_data} if not isinstance(end_data, dict) else end_data)
                if end_entity.get("id") and end_entity["id"] != entity_id:
                    neighbors[end_entity["id"]] = end_entity

                rels = row.get("relationships(path)", [])
                if isinstance(rels, list):
                    for rel in rels:
                        rel_data = self._parse_relationship(rel)
                        if rel_data and rel_data.get("weight", 1) >= min_weight:
                            relationships.append(rel_data)

        return {
            "entity": start_entity,
            "neighbors": list(neighbors.values()),
            "relationships": relationships,
            "depth": depth,
        }

    async def shortest_path(
        self, from_id: str, to_id: str
    ) -> dict[str, Any] | None:
        """Find the shortest path between two entities.

        Args:
            from_id: Starting entity AGE vertex ID.
            to_id: Target entity AGE vertex ID.

        Returns:
            Dict with path (list of entities), relationships, and
            total_weight, or None if no path exists.
        """
        cypher = (
            f"MATCH path = shortestPath("
            f"(a:Entity)-[*]-(b:Entity)"
            f") "
            f"WHERE id(a) = {from_id} AND id(b) = {to_id} "
            f"RETURN nodes(path), relationships(path)"
        )
        results = await self._cypher(cypher)

        if not results:
            return None

        row = results[0]
        nodes_raw = row.get("nodes(path)", [])
        rels_raw = row.get("relationships(path)", [])

        path_entities = []
        if isinstance(nodes_raw, list):
            for node in nodes_raw:
                entity = self._parse_entity(node if isinstance(node, dict) else {"value": node})
                path_entities.append(entity)

        path_rels = []
        total_weight = 0.0
        if isinstance(rels_raw, list):
            for rel in rels_raw:
                rel_data = self._parse_relationship(rel)
                if rel_data:
                    path_rels.append(rel_data)
                    total_weight += rel_data.get("weight", 1)

        return {
            "path": path_entities,
            "relationships": path_rels,
            "total_weight": total_weight,
        }

    async def get_entity_documents(
        self, entity_id: str
    ) -> list[dict[str, Any]]:
        """Get documents mentioning an entity.

        Args:
            entity_id: The AGE vertex ID of the entity.

        Returns:
            List of document summary dicts.
        """
        # Get document IDs from the graph
        results = await self._cypher(
            f"MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document) "
            f"WHERE id(e) = {entity_id} "
            f"RETURN d.doc_id"
        )

        doc_ids: list[uuid.UUID] = []
        for row in results:
            doc_id_str = row.get("value", row.get("doc_id", ""))
            if isinstance(doc_id_str, str):
                try:
                    doc_ids.append(uuid.UUID(doc_id_str))
                except ValueError:
                    continue

        if not doc_ids:
            return []

        # Query the relational table for full document data
        stmt = (
            select(
                ProcessedDocument.id,
                ProcessedDocument.title,
                ProcessedDocument.summary,
                ProcessedDocument.category,
                ProcessedDocument.created_at,
            )
            .where(
                ProcessedDocument.id.in_(doc_ids),
                ProcessedDocument.is_current.is_(True),
            )
            .order_by(ProcessedDocument.created_at.desc())
        )
        result = await self.db.execute(stmt)
        rows = result.mappings().all()

        return [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "summary": row["summary"],
                "category": row["category"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in rows
        ]

    async def get_relationships(
        self,
        relationship_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List relationships, optionally filtered by type.

        Args:
            relationship_type: Optional relationship type filter.
            limit: Maximum number of results.

        Returns:
            List of relationship dicts with source and target entities.
        """
        if relationship_type:
            safe_type = re.sub(r"[^A-Za-z0-9_]", "_", relationship_type).upper()
            cypher = (
                f"MATCH (s:Entity)-[r:{safe_type}]->(t:Entity) "
                f"RETURN s, r, t "
                f"ORDER BY r.weight DESC "
                f"LIMIT {limit}"
            )
        else:
            cypher = (
                f"MATCH (s:Entity)-[r]->(t:Entity) "
                f"RETURN s, r, t "
                f"ORDER BY r.weight DESC "
                f"LIMIT {limit}"
            )

        results = await self._cypher(cypher)

        relationships = []
        for row in results:
            rel_data = self._parse_relationship(row)
            if rel_data:
                relationships.append(rel_data)

        return relationships

    # ── Statistics ────────────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        """Get graph statistics: node counts, edge counts, by type.

        Returns:
            Dict with total_entities, total_relationships,
            entities_by_type, relationships_by_type.
        """
        stats: dict[str, Any] = {
            "total_entities": 0,
            "total_relationships": 0,
            "entities_by_type": {},
            "relationships_by_type": {},
        }

        if not await self._check_age_available():
            return stats

        # Count entities by type
        entity_results = await self._cypher(
            "MATCH (e:Entity) "
            "RETURN e.entity_type AS entity_type, count(e) AS cnt"
        )
        for row in entity_results:
            etype = row.get("entity_type", row.get("value", "unknown"))
            cnt = row.get("cnt", row.get("value", 0))
            if isinstance(etype, str) and isinstance(cnt, (int, float)):
                stats["entities_by_type"][etype] = int(cnt)
                stats["total_entities"] += int(cnt)

        # Count relationships by type
        rel_results = await self._cypher(
            "MATCH ()-[r]->() "
            "RETURN type(r) AS rel_type, count(r) AS cnt"
        )
        for row in rel_results:
            rtype = row.get("rel_type", row.get("value", "unknown"))
            cnt = row.get("cnt", row.get("value", 0))
            if isinstance(rtype, str) and isinstance(cnt, (int, float)):
                stats["relationships_by_type"][rtype] = int(cnt)
                stats["total_relationships"] += int(cnt)

        return stats

    # ── Rebuild ───────────────────────────────────────────────────────────

    async def rebuild_graph(self) -> dict[str, Any]:
        """Rebuild the entire graph from processed documents.

        Clears the graph and re-inserts all entities and relationships
        from current ProcessedDocument records.

        Returns:
            Dict with entity_count and relationship_count.
        """
        if not await self._check_age_available():
            return {"entity_count": 0, "relationship_count": 0, "error": "AGE not available"}

        # Clear all vertices and edges
        await self._cypher("MATCH (n) DETACH DELETE n")

        logger.info("graph_rebuild_started")

        # Iterate all current documents
        stmt = (
            select(ProcessedDocument)
            .where(ProcessedDocument.is_current.is_(True))
        )
        result = await self.db.execute(stmt)
        documents = result.scalars().all()

        entity_count = 0
        relationship_count = 0

        for doc in documents:
            entities = doc.entities if isinstance(doc.entities, list) else []
            # Look for relationships in frontmatter or entities structure
            relationships: list[dict[str, Any]] = []
            if isinstance(doc.frontmatter, dict):
                relationships = doc.frontmatter.get("relationships", [])

            for entity in entities:
                if isinstance(entity, dict) and entity.get("name"):
                    await self.upsert_entity(
                        name=entity["name"],
                        entity_type=entity.get("type", "UNKNOWN"),
                        document_id=doc.id,
                        properties=entity.get("properties"),
                    )
                    entity_count += 1

            for rel in relationships:
                if isinstance(rel, dict) and rel.get("source_entity") and rel.get("target_entity"):
                    await self.add_relationship(
                        source_name=rel["source_entity"],
                        target_name=rel["target_entity"],
                        relationship_type=rel.get("relationship_type", "RELATED_TO"),
                        description=rel.get("description", ""),
                        confidence=rel.get("confidence", 0.5),
                        document_id=doc.id,
                    )
                    relationship_count += 1

        logger.info(
            "graph_rebuild_completed",
            documents=len(documents),
            entities=entity_count,
            relationships=relationship_count,
        )

        return {
            "entity_count": entity_count,
            "relationship_count": relationship_count,
        }

    # ── Result Parsing Helpers ────────────────────────────────────────────

    @staticmethod
    def _parse_entity(raw: dict[str, Any]) -> dict[str, Any]:
        """Parse an AGE entity vertex into a clean dict.

        Args:
            raw: Raw agtype result dict.

        Returns:
            Standardized entity dict.
        """
        # AGE results can be nested; try to extract the vertex properties
        props = raw
        if "value" in raw and isinstance(raw["value"], dict):
            props = raw["value"]

        return {
            "id": str(props.get("id", "")),
            "name": props.get("name", ""),
            "entity_type": props.get("entity_type", ""),
            "canonical_name": props.get("canonical_name", ""),
            "document_count": props.get("document_count", 0),
            "first_seen_at": props.get("first_seen_at"),
            "properties": {
                k: v
                for k, v in props.items()
                if k not in ("id", "name", "entity_type", "canonical_name",
                             "document_count", "first_seen_at", "label")
            },
        }

    @staticmethod
    def _parse_relationship(raw: Any) -> dict[str, Any] | None:
        """Parse an AGE relationship edge into a clean dict.

        Args:
            raw: Raw agtype result (dict or other).

        Returns:
            Standardized relationship dict, or None if unparseable.
        """
        if not isinstance(raw, dict):
            return None

        # Try to extract source, relationship, and target from the row
        source = raw.get("s", raw.get("source", raw.get("e", {})))
        target = raw.get("t", raw.get("target", raw.get("other", {})))
        rel = raw.get("r", raw.get("relationship", raw))

        if isinstance(source, dict) and isinstance(target, dict):
            source_entity = GraphService._parse_entity(
                source if "name" in source else {"value": source}
            )
            target_entity = GraphService._parse_entity(
                target if "name" in target else {"value": target}
            )
        else:
            return None

        rel_props = rel if isinstance(rel, dict) else {}

        return {
            "id": str(rel_props.get("id", "")),
            "source": source_entity,
            "target": target_entity,
            "relationship_type": rel_props.get("label", rel_props.get("type", "")),
            "description": rel_props.get("description", ""),
            "confidence": rel_props.get("confidence", 0.0),
            "weight": rel_props.get("weight", 1),
            "source_document_id": rel_props.get("source_document_id"),
        }

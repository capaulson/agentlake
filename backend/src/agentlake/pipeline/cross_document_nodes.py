"""Cross-document analysis nodes — GPT-5.4 single-pass version.

With 1M context, we send ALL document metadata (entities, people,
relationships, tags, summaries, dates, metrics) in one shot and get
back a comprehensive cross-corpus analysis.

Old pipeline: gather → map_entities → [3 parallel LLM calls] → synthesize → store
New pipeline: gather → single_pass_analysis → store
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.config import get_settings
from agentlake.core.database import _get_session_factory
from agentlake.models.document import ProcessedDocument
from agentlake.models.diff_log import DiffLog, DiffType
from agentlake.pipeline.cross_document_state import (
    CrossDocRelationship,
    CrossDocState,
    DocumentSummary,
    EntityMention,
    Insight,
    ThematicCluster,
)
from agentlake.pipeline.nodes import _parse_yaml_or_json, _strip_reasoning
from agentlake.services.llm_client import LLMClient

logger = structlog.get_logger(__name__)


def _get_llm_client() -> LLMClient:
    settings = get_settings()
    return LLMClient(
        gateway_url=settings.LLM_GATEWAY_URL,
        service_token=settings.LLM_GATEWAY_SERVICE_TOKEN,
        service_name="cross_doc_analyzer",
    )


# ═══════════════════════════════════════════════════════════════════════════
# NODE: Gather Documents (with rich frontmatter)
# ═══════════════════════════════════════════════════════════════════════════


async def gather_documents_node(state: CrossDocState) -> dict:
    """Collect all documents with their full extracted metadata."""
    scope = state.get("scope", "all")
    max_docs = state.get("max_documents", 100)
    log = logger.bind(stage="gather", scope=scope)
    log.info("gather_started")

    settings = get_settings()
    session_factory = _get_session_factory(settings)

    async with session_factory() as db:
        query = (
            select(ProcessedDocument)
            .where(ProcessedDocument.is_current == True)  # noqa: E712
            .order_by(ProcessedDocument.created_at.desc())
            .limit(max_docs)
        )
        if scope.startswith("category:"):
            query = query.where(ProcessedDocument.category == scope.split(":", 1)[1])

        result = await db.execute(query)
        docs = result.scalars().all()

        documents = []
        for doc in docs:
            fm = doc.frontmatter if isinstance(doc.frontmatter, dict) else {}
            documents.append(DocumentSummary(
                id=str(doc.id),
                title=doc.title,
                summary=doc.summary[:500] if doc.summary else "",
                category=doc.category,
                entities=doc.entities if isinstance(doc.entities, list) else [],
                source_file_id=str(doc.source_file_id),
            ))

    log.info("gather_complete", count=len(documents))
    return {
        "documents": documents,
        "document_count": len(documents),
        "current_stage": "gathering",
    }


# ═══════════════════════════════════════════════════════════════════════════
# NODE: Single-Pass Cross-Document Analysis
# ═══════════════════════════════════════════════════════════════════════════

CROSS_DOC_SYSTEM_PROMPT = """You are an expert intelligence analyst examining a corpus of corporate documents.

You have access to extracted metadata from every document: entities, people, relationships, tags, dates, metrics, sections, and summaries.

Analyze the ENTIRE corpus and produce a comprehensive intelligence report as a JSON object:

```json
{
  "entity_network": [
    {
      "name": "Entity name",
      "canonical_name": "lowercase canonical",
      "type": "person|organization|product|technology",
      "document_count": 5,
      "total_mentions": 12,
      "roles_observed": ["CTO", "audit authorizer"],
      "key_connections": ["entity B", "entity C"],
      "summary": "One paragraph synthesis of what this entity does across all documents"
    }
  ],

  "cross_document_relationships": [
    {
      "source": "Entity A",
      "target": "Entity B",
      "type": "partners_with|works_at|manages|competes_with|...",
      "description": "Relationship description synthesized across documents",
      "confidence": 0.95,
      "evidence_documents": ["doc title 1", "doc title 2"],
      "evidence_quotes": ["supporting quote from doc 1"]
    }
  ],

  "thematic_clusters": [
    {
      "theme": "Short theme name",
      "description": "What connects these documents",
      "document_titles": ["doc 1", "doc 2"],
      "key_entities": ["entity A", "entity B"],
      "key_dates": ["2024-Q4"],
      "importance": "high|medium|low"
    }
  ],

  "insights": [
    {
      "title": "Insight title",
      "description": "Detailed insight with specific evidence",
      "type": "trend|contradiction|gap|connection|risk|opportunity|recommendation",
      "confidence": 0.9,
      "supporting_documents": ["doc title 1", "doc title 2"],
      "entities_involved": ["entity A"],
      "action_items": ["what should be done about this"]
    }
  ],

  "timeline": [
    {
      "date": "2024-11-28",
      "event": "What happened",
      "documents": ["doc title"],
      "entities": ["who was involved"]
    }
  ],

  "people_directory": [
    {
      "name": "Full name",
      "roles": ["CTO", "Audit Lead"],
      "organizations": ["NovaTech"],
      "email": "email if found",
      "appears_in": 5,
      "key_activities": ["Led security audit", "Authorized migration"],
      "connections": ["person B — collaborates on security"]
    }
  ],

  "risk_register": [
    {
      "risk": "Description of the risk",
      "severity": "critical|high|medium|low",
      "source_documents": ["doc title"],
      "mitigations": ["what's being done"],
      "owner": "person name if identified"
    }
  ],

  "corpus_summary": "2-3 paragraph executive summary of the entire document corpus — what the organization is doing, key themes, major decisions, and open questions"
}
```

## Rules
1. **Synthesize across documents** — don't just list per-document findings. Connect the dots.
2. **Entity deduplication** — merge "NovaTech", "Novatech", "NovaTech Inc." into one entity.
3. **People directory** — merge all mentions of the same person across documents.
4. **Evidence-based** — every insight and relationship must cite specific documents.
5. **Contradictions** — flag when documents disagree (e.g., different dates for the same event).
6. **Timeline** — build a chronological timeline of events across all documents.
7. **Risks** — identify risks, security issues, compliance gaps mentioned anywhere.
8. **Be exhaustive** — this is an intelligence report. Missing a connection is worse than including a weak one.

Return ONLY the JSON object."""


async def single_pass_analysis_node(state: CrossDocState) -> dict:
    """Send all document metadata to GPT-5.4 for comprehensive cross-corpus analysis."""
    documents = state["documents"]
    log = logger.bind(stage="single_pass_analysis", doc_count=len(documents))
    log.info("cross_doc_analysis_started")

    if len(documents) < 2:
        return {
            "entity_map": [], "relationships": [], "clusters": [],
            "contradictions": [], "connections": [], "insights": [],
            "current_stage": "complete", "llm_calls_made": 0, "total_tokens_used": 0,
        }

    # Build the corpus summary for the LLM — include ALL rich metadata
    settings = get_settings()
    session_factory = _get_session_factory(settings)

    doc_descriptions = []
    async with session_factory() as db:
        for doc_summary in documents:
            result = await db.execute(
                select(ProcessedDocument).where(ProcessedDocument.id == uuid.UUID(doc_summary["id"]))
            )
            doc = result.scalar_one_or_none()
            if not doc:
                continue

            fm = doc.frontmatter if isinstance(doc.frontmatter, dict) else {}
            entities = doc.entities if isinstance(doc.entities, list) else []
            people = fm.get("people", [])
            relationships = fm.get("relationships", [])
            tags = fm.get("tags", [])
            dates = fm.get("dates", [])
            metrics = fm.get("metrics", [])
            sections = fm.get("sections", [])
            cross_refs = fm.get("cross_references", [])
            key_quotes = fm.get("key_quotes", [])

            desc = f"""### {doc.title}
**Category:** {doc.category} | **File:** {doc_summary['source_file_id'][:8]}

**Summary:** {doc.summary[:400]}

**Entities ({len(entities)}):** {json.dumps([{'name': e.get('name'), 'type': e.get('type'), 'context': e.get('context','')} for e in entities[:20]], default=str)[:1000]}

**People ({len(people)}):** {json.dumps(people[:10], default=str)[:500]}

**Relationships ({len(relationships)}):** {json.dumps([{'source': r.get('source'), 'target': r.get('target'), 'type': r.get('type'), 'description': r.get('description','')} for r in relationships[:15]], default=str)[:800]}

**Tags:** {', '.join(tags[:15]) if isinstance(tags, list) else ''}

**Dates:** {json.dumps(dates[:8], default=str)[:300] if isinstance(dates, list) else ''}

**Metrics:** {json.dumps(metrics[:8], default=str)[:300] if isinstance(metrics, list) else ''}

**Cross-references:** {', '.join(str(x) for x in cross_refs[:5]) if isinstance(cross_refs, list) else ''}

**Key Quotes:** {json.dumps(key_quotes[:3], default=str)[:300] if isinstance(key_quotes, list) else ''}

**Sections:** {', '.join(s.get('heading','') for s in sections[:10]) if isinstance(sections, list) else ''}
"""
            doc_descriptions.append(desc)

    corpus_text = f"# Document Corpus ({len(doc_descriptions)} documents)\n\n" + "\n\n---\n\n".join(doc_descriptions)

    log.info("sending_corpus_to_llm", corpus_length=len(corpus_text), doc_count=len(doc_descriptions))

    llm = _get_llm_client()
    try:
        result = await llm.complete(
            messages=[
                {"role": "system", "content": CROSS_DOC_SYSTEM_PROMPT},
                {"role": "user", "content": corpus_text},
            ],
            purpose="summarize",
            max_tokens=32000,
            temperature=0.2,
        )
        tokens = result.total_tokens
        raw = _strip_reasoning(result.content)
        analysis = _parse_yaml_or_json(raw)

        if isinstance(analysis, list) and len(analysis) > 0 and isinstance(analysis[0], dict):
            analysis = analysis[0]
        if not isinstance(analysis, dict):
            log.warning("cross_doc_parse_failed", type=type(analysis).__name__)
            analysis = {}

    except Exception as e:
        log.error("cross_doc_analysis_failed", error=str(e))
        analysis = {}
        tokens = 0

    await llm.close()

    # Extract results
    entity_network = analysis.get("entity_network", [])
    cross_rels = analysis.get("cross_document_relationships", [])
    clusters = analysis.get("thematic_clusters", [])
    insights_raw = analysis.get("insights", [])
    timeline = analysis.get("timeline", [])
    people_dir = analysis.get("people_directory", [])
    risk_register = analysis.get("risk_register", [])
    corpus_summary = analysis.get("corpus_summary", "")

    # Convert to state types
    entity_map = [
        EntityMention(
            name=e.get("name", ""),
            canonical_name=e.get("canonical_name", e.get("name", "").lower()),
            entity_type=e.get("type", "unknown"),
            document_ids=[],
            mention_count=e.get("total_mentions", e.get("document_count", 1)),
            contexts=[e.get("summary", "")],
        )
        for e in entity_network if isinstance(e, dict) and e.get("name")
    ]

    relationships = [
        CrossDocRelationship(
            source_entity=r.get("source", ""),
            target_entity=r.get("target", ""),
            relationship_type=r.get("type", "related_to"),
            description=r.get("description", ""),
            confidence=float(r.get("confidence", 0.5)),
            evidence=[{"document_id": "", "snippet": d} for d in r.get("evidence_documents", [])[:3]],
        )
        for r in cross_rels if isinstance(r, dict)
    ]

    theme_clusters = [
        ThematicCluster(
            theme=c.get("theme", ""),
            description=c.get("description", ""),
            document_ids=c.get("document_titles", []),
            key_entities=c.get("key_entities", []),
        )
        for c in clusters if isinstance(c, dict)
    ]

    all_insights = []
    for item in insights_raw:
        if isinstance(item, dict) and item.get("title"):
            all_insights.append(Insight(
                title=item["title"],
                description=item.get("description", ""),
                insight_type=item.get("type", "connection"),
                confidence=float(item.get("confidence", 0.5)),
                supporting_documents=item.get("supporting_documents", []),
                entities_involved=item.get("entities_involved", []),
            ))

    contradictions = [i for i in all_insights if i["insight_type"] == "contradiction"]
    connections = [i for i in all_insights if i["insight_type"] != "contradiction"]

    log.info(
        "cross_doc_analysis_complete",
        entities=len(entity_map),
        relationships=len(relationships),
        clusters=len(theme_clusters),
        insights=len(all_insights),
        timeline_events=len(timeline),
        people=len(people_dir),
        risks=len(risk_register),
        tokens=tokens,
    )

    return {
        "entity_map": entity_map,
        "relationships": relationships,
        "clusters": theme_clusters,
        "contradictions": contradictions,
        "connections": connections,
        "insights": all_insights,
        # Store the full analysis for the insights document
        "insight_document_markdown": _build_insights_markdown(
            analysis, documents, entity_map, relationships,
            theme_clusters, all_insights, timeline, people_dir, risk_register, corpus_summary, state, tokens,
        ),
        "current_stage": "analyzed",
        "llm_calls_made": 1,
        "total_tokens_used": tokens,
    }


def _build_insights_markdown(
    analysis, documents, entity_map, relationships,
    clusters, insights, timeline, people_dir, risk_register, corpus_summary, state, tokens,
) -> str:
    """Build the insights report markdown from analysis results."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [f"# Cross-Document Intelligence Report\n\n**Generated:** {now}\n**Documents analyzed:** {len(documents)}\n**Model:** GPT-5.4 single-pass\n"]

    if corpus_summary:
        parts.append(f"## Executive Summary\n\n{corpus_summary}\n")

    # People directory
    if people_dir:
        parts.append(f"## People Directory ({len(people_dir)})\n")
        for p in people_dir:
            if isinstance(p, dict) and p.get("name"):
                roles = ", ".join(p.get("roles", [])) if isinstance(p.get("roles"), list) else ""
                email = p.get("email", "")
                appears = p.get("appears_in", 0)
                activities = p.get("key_activities", [])
                connections = p.get("connections", [])
                parts.append(f"### {p['name']}")
                if roles: parts.append(f"**Roles:** {roles}")
                if email: parts.append(f"**Email:** {email}")
                parts.append(f"**Appears in:** {appears} documents")
                if activities:
                    parts.append("**Key activities:**\n" + "\n".join(f"- {a}" for a in activities[:5]))
                if connections:
                    parts.append("**Connections:**\n" + "\n".join(f"- {c}" for c in connections[:5]))
                parts.append("")

    # Entity network
    if entity_map:
        parts.append(f"## Entity Network ({len(entity_map)} entities)\n")
        for e in sorted(entity_map, key=lambda x: x.get("mention_count", 0), reverse=True)[:25]:
            parts.append(f"- **{e['name']}** ({e['entity_type']}) — {e['mention_count']} mentions")
        parts.append("")

    # Cross-document relationships
    if relationships:
        parts.append(f"## Cross-Document Relationships ({len(relationships)})\n")
        for r in relationships[:20]:
            parts.append(f"- **{r['source_entity']}** → *{r['relationship_type']}* → **{r['target_entity']}** ({r['confidence']:.0%})")
            parts.append(f"  {r['description']}")
        parts.append("")

    # Thematic clusters
    if clusters:
        parts.append(f"## Thematic Clusters ({len(clusters)})\n")
        for c in clusters:
            parts.append(f"### {c['theme']}\n{c['description']}\n- Documents: {len(c.get('document_ids', []))}\n- Entities: {', '.join(c.get('key_entities', [])[:5])}\n")

    # Timeline
    if timeline:
        parts.append(f"## Timeline ({len(timeline)} events)\n")
        for event in sorted(timeline, key=lambda x: str(x.get("date", "")))[:30]:
            if isinstance(event, dict):
                parts.append(f"- **{event.get('date', '?')}** — {event.get('event', '')}")
        parts.append("")

    # Insights
    if insights:
        type_icons = {"trend": "📈", "contradiction": "⚠️", "gap": "❓", "connection": "🔗",
                      "risk": "🚨", "opportunity": "💡", "recommendation": "✅"}
        parts.append(f"## Insights ({len(insights)})\n")
        for i in sorted(insights, key=lambda x: x["confidence"], reverse=True):
            icon = type_icons.get(i["insight_type"], "📌")
            parts.append(f"### {icon} {i['title']}\n**Type:** {i['insight_type']} | **Confidence:** {i['confidence']:.0%}\n\n{i['description']}\n")

    # Risk register
    if risk_register:
        parts.append(f"## Risk Register ({len(risk_register)})\n")
        for r in risk_register:
            if isinstance(r, dict):
                sev = r.get("severity", "?")
                parts.append(f"- **[{sev.upper()}]** {r.get('risk', '')}")
                if r.get("owner"): parts.append(f"  Owner: {r['owner']}")
                if r.get("mitigations"): parts.append(f"  Mitigations: {', '.join(r['mitigations'][:3])}")
        parts.append("")

    # Stats
    parts.append(f"\n## Analysis Stats\n- Documents: {len(documents)}\n- Entities: {len(entity_map)}\n- Relationships: {len(relationships)}\n- Clusters: {len(clusters)}\n- Insights: {len(insights)}\n- Timeline events: {len(timeline)}\n- People: {len(people_dir)}\n- Risks: {len(risk_register)}\n- Tokens: {tokens}\n")

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# NODE: Update Entity Graph
# ═══════════════════════════════════════════════════════════════════════════


async def update_graph_node(state: CrossDocState) -> dict:
    """Persist discovered relationships to the entity graph."""
    relationships = state.get("relationships", [])
    entity_map = state.get("entity_map", [])
    log = logger.bind(stage="update_graph")

    if not relationships and not entity_map:
        return {"graph_updates": 0}

    log.info("update_graph_started", relationships=len(relationships), entities=len(entity_map))
    updates = 0

    try:
        settings = get_settings()
        session_factory = _get_session_factory(settings)
        async with session_factory() as db:
            from agentlake.services.graph import GraphService
            graph = GraphService(db, settings.GRAPH_NAME)

            for ent in entity_map[:50]:
                try:
                    await graph.upsert_entity(ent["name"], ent["entity_type"], uuid.uuid4())
                    updates += 1
                except Exception:
                    pass

            for rel in relationships[:50]:
                try:
                    await graph.add_relationship(
                        rel["source_entity"], rel["target_entity"],
                        rel["relationship_type"], rel["description"],
                        rel["confidence"], uuid.uuid4(),
                    )
                    updates += 1
                except Exception:
                    pass

            await db.commit()
    except Exception as e:
        log.warning("update_graph_failed", error=str(e))

    log.info("update_graph_complete", updates=updates)
    return {"graph_updates": updates}


# ═══════════════════════════════════════════════════════════════════════════
# NODE: Store Insights Document
# ═══════════════════════════════════════════════════════════════════════════


async def store_insights_node(state: CrossDocState) -> dict:
    """Persist the insights report as a ProcessedDocument."""
    markdown = state.get("insight_document_markdown", "")
    log = logger.bind(stage="store_insights")

    if not markdown:
        return {"insight_document_id": None}

    log.info("store_insights_started")
    settings = get_settings()
    session_factory = _get_session_factory(settings)

    async with session_factory() as db:
        from agentlake.models.file import File, FileStatus
        system_file_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        system_file = await db.get(File, system_file_id)
        if system_file is None:
            system_file = File(
                id=system_file_id, filename="system:analysis", original_filename="system:analysis",
                content_type="application/x-agentlake-generated", size_bytes=0,
                sha256_hash="0" * 64, storage_key="system/analysis", status=FileStatus.PROCESSED,
            )
            db.add(system_file)
            await db.flush()

        doc = ProcessedDocument(
            source_file_id=system_file_id,
            title=f"Cross-Document Intelligence Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            summary=f"GPT-5.4 single-pass analysis of {state.get('document_count', 0)} documents. "
                    f"Found {len(state.get('entity_map', []))} cross-doc entities, "
                    f"{len(state.get('relationships', []))} relationships, "
                    f"{len(state.get('clusters', []))} thematic clusters, "
                    f"and {len(state.get('insights', []))} insights.",
            category="research",
            body_markdown=markdown,
            frontmatter={
                "generated": True, "analysis_type": "cross_document_intelligence",
                "scope": state.get("scope", "all"),
                "document_count": state.get("document_count", 0),
                "entity_count": len(state.get("entity_map", [])),
                "relationship_count": len(state.get("relationships", [])),
                "cluster_count": len(state.get("clusters", [])),
                "insight_count": len(state.get("insights", [])),
            },
            entities=[{"name": e["name"], "type": e["entity_type"]} for e in state.get("entity_map", [])[:30]],
            version=1, is_current=True, processing_version=settings.PROCESSING_VERSION,
        )
        db.add(doc)
        await db.flush()

        await db.execute(text("""
            UPDATE processed_documents SET search_vector =
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(left(body_markdown, 10000), '')), 'C')
            WHERE id = :doc_id
        """), {"doc_id": doc.id})

        await db.commit()
        log.info("store_insights_complete", document_id=str(doc.id))
        return {"insight_document_id": str(doc.id), "current_stage": "complete"}

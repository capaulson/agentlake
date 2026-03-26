"""Folder-scoped AI analysis pipeline.

Generates an AI summary for a specific folder by analyzing all documents
within it, then triggers a rollup on the parent folder.

    analyze_folder(folder_id)
      → gather folder's documents
      → GPT-5.4 single-pass analysis (scoped to folder contents)
      → store as ProcessedDocument linked to folder.ai_summary_id
      → trigger parent folder rollup
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.config import get_settings
from agentlake.core.database import _get_session_factory
from agentlake.models.document import ProcessedDocument
from agentlake.models.folder import Folder
from agentlake.models.file import File
from agentlake.pipeline.nodes import _parse_yaml_or_json, _strip_reasoning
from agentlake.services.llm_client import LLMClient

logger = structlog.get_logger(__name__)

FOLDER_ANALYSIS_PROMPT = """You are analyzing all documents within a specific folder of a corporate data lake.
The folder represents a logical grouping (e.g., a partner, project, or topic).

Analyze ALL the documents and produce a comprehensive folder summary as JSON:

```json
{
  "executive_summary": "3-5 sentence overview of what this folder contains and why it matters",
  "key_findings": ["Most important finding 1", "Finding 2", ...],
  "people_involved": [
    {"name": "...", "role": "...", "involvement": "what they did in this context"}
  ],
  "entities": [
    {"name": "...", "type": "...", "relevance": "why this entity matters in this folder's context"}
  ],
  "timeline": [
    {"date": "...", "event": "..."}
  ],
  "action_items": ["Open action item 1", ...],
  "risks_and_issues": ["Risk or issue 1", ...],
  "relationships": [
    {"source": "...", "target": "...", "type": "...", "description": "..."}
  ],
  "tags": ["tag1", "tag2"],
  "status": "active|completed|on-hold|archived",
  "next_steps": ["What should happen next 1", ...]
}
```

Be specific, cite document titles, and focus on what's actionable.
Return ONLY the JSON object."""


async def analyze_folder(folder_id: str) -> dict:
    """Run GPT-5.4 analysis on a folder's contents."""
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    log = logger.bind(folder_id=folder_id)
    log.info("folder_analysis_started")

    async with session_factory() as db:
        # Get the folder
        folder = await db.get(Folder, uuid.UUID(folder_id))
        if not folder:
            log.warning("folder_not_found")
            return {"error": "folder_not_found"}

        # Get all files in this folder (and subfolders)
        file_ids = await db.execute(text("""
            WITH RECURSIVE folder_tree AS (
                SELECT id FROM folders WHERE id = :fid
                UNION ALL
                SELECT f.id FROM folders f JOIN folder_tree ft ON f.parent_id = ft.id
            )
            SELECT fi.id FROM files fi
            WHERE fi.folder_id IN (SELECT id FROM folder_tree)
              AND fi.deleted_at IS NULL
              AND fi.status = 'processed'
        """), {"fid": folder_id})
        file_id_list = [str(r[0]) for r in file_ids.fetchall()]

        if not file_id_list:
            log.info("folder_empty_no_processed_files", folder=folder.name)
            return {"error": "no_processed_files", "folder": folder.name}

        # Get processed documents for these files
        docs = []
        for fid in file_id_list:
            result = await db.execute(
                select(ProcessedDocument)
                .where(ProcessedDocument.source_file_id == uuid.UUID(fid))
                .where(ProcessedDocument.is_current == True)  # noqa: E712
            )
            doc = result.scalar_one_or_none()
            if doc:
                fm = doc.frontmatter if isinstance(doc.frontmatter, dict) else {}
                docs.append({
                    "title": doc.title,
                    "summary": doc.summary[:500] if doc.summary else "",
                    "category": doc.category,
                    "entities": doc.entities[:20] if isinstance(doc.entities, list) else [],
                    "people": fm.get("people", [])[:10],
                    "relationships": fm.get("relationships", [])[:10],
                    "tags": fm.get("tags", [])[:10],
                    "dates": fm.get("dates", [])[:5],
                    "key_quotes": fm.get("key_quotes", [])[:3],
                })

    if not docs:
        return {"error": "no_documents", "folder": folder.name}

    log.info("folder_analysis_sending_to_llm", folder=folder.name, doc_count=len(docs))

    # Build the prompt
    doc_descriptions = []
    for d in docs:
        desc = f"### {d['title']}\n**Category:** {d['category']}\n**Summary:** {d['summary'][:300]}"
        if d.get("people"):
            desc += f"\n**People:** {json.dumps(d['people'][:5], default=str)[:300]}"
        if d.get("entities"):
            desc += f"\n**Entities:** {json.dumps([e.get('name','') for e in d['entities'][:8]], default=str)}"
        if d.get("tags"):
            desc += f"\n**Tags:** {', '.join(str(t) for t in d['tags'][:8])}"
        if d.get("key_quotes"):
            desc += f"\n**Key quote:** \"{d['key_quotes'][0][:150] if d['key_quotes'] else ''}\""
        doc_descriptions.append(desc)

    corpus = f"# Folder: {folder.name}\n**Path:** {folder.path}\n**Documents:** {len(docs)}\n\n" + "\n\n---\n\n".join(doc_descriptions)

    # Call GPT-5.4
    llm = LLMClient(
        gateway_url=settings.LLM_GATEWAY_URL,
        service_token=settings.LLM_GATEWAY_SERVICE_TOKEN,
        service_name="folder_analyzer",
    )

    try:
        result = await llm.complete(
            messages=[
                {"role": "system", "content": FOLDER_ANALYSIS_PROMPT},
                {"role": "user", "content": corpus},
            ],
            purpose="summarize",
            max_tokens=8000,
            temperature=0.2,
        )
        tokens = result.total_tokens
        analysis = _parse_yaml_or_json(_strip_reasoning(result.content))
        if isinstance(analysis, list) and analysis:
            analysis = analysis[0]
        if not isinstance(analysis, dict):
            analysis = {}
    except Exception as e:
        log.error("folder_analysis_llm_failed", error=str(e))
        analysis = {}
        tokens = 0

    await llm.close()

    # Build markdown summary
    summary_md = _build_folder_markdown(folder, analysis, docs, tokens)

    # Store as ProcessedDocument
    async with session_factory() as db:
        # Get or create system file for generated content
        system_file_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        system_file = await db.get(File, system_file_id)
        if not system_file:
            from agentlake.models.file import FileStatus
            system_file = File(
                id=system_file_id, filename="system:analysis", original_filename="system:analysis",
                content_type="application/x-agentlake-generated", size_bytes=0,
                sha256_hash="0" * 64, storage_key="system/analysis", status=FileStatus.PROCESSED,
            )
            db.add(system_file)
            await db.flush()

        # Delete old summary if exists
        if folder.ai_summary_id:
            old_doc = await db.get(ProcessedDocument, folder.ai_summary_id)
            if old_doc:
                await db.delete(old_doc)
                await db.flush()

        # Create new summary document
        doc = ProcessedDocument(
            source_file_id=system_file_id,
            title=f"📋 {folder.name} — AI Summary",
            summary=analysis.get("executive_summary", f"AI-generated summary of {len(docs)} documents in {folder.name}"),
            category="reference",
            body_markdown=summary_md,
            frontmatter={
                "generated": True,
                "analysis_type": "folder_summary",
                "folder_id": folder_id,
                "folder_path": folder.path,
                "document_count": len(docs),
                "analysis": analysis,
                "tokens_used": tokens,
            },
            entities=[{"name": e.get("name",""), "type": e.get("type","")} for e in analysis.get("entities", [])[:20]],
            version=1,
            is_current=True,
            processing_version=settings.PROCESSING_VERSION,
        )
        db.add(doc)
        await db.flush()

        # Update search vector
        await db.execute(text("""
            UPDATE processed_documents SET search_vector =
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(left(body_markdown, 10000), '')), 'C')
            WHERE id = :doc_id
        """), {"doc_id": doc.id})

        # Link to folder
        folder_obj = await db.get(Folder, uuid.UUID(folder_id))
        if folder_obj:
            folder_obj.ai_summary_id = doc.id

        await db.commit()
        log.info("folder_analysis_complete", folder=folder.name, doc_id=str(doc.id), tokens=tokens,
                 entities=len(analysis.get("entities", [])), people=len(analysis.get("people_involved", [])))

    # Trigger parent folder rollup
    if folder.parent_id:
        try:
            from agentlake.workers.celery_app import celery_app
            celery_app.send_task("analyze_folder", kwargs={"folder_id": str(folder.parent_id)}, queue="low")
            log.info("parent_rollup_triggered", parent_id=str(folder.parent_id))
        except Exception:
            pass

    return {
        "folder": folder.name,
        "path": folder.path,
        "documents_analyzed": len(docs),
        "doc_id": str(doc.id),
        "tokens": tokens,
    }


def _build_folder_markdown(folder, analysis: dict, docs: list, tokens: int) -> str:
    """Build the markdown summary for a folder."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        f"# {folder.name}\n\n**Path:** `{folder.path}`\n**Generated:** {now}\n**Documents:** {len(docs)}\n",
    ]

    if analysis.get("executive_summary"):
        parts.append(f"## Executive Summary\n\n{analysis['executive_summary']}\n")

    if analysis.get("status"):
        parts.append(f"**Status:** {analysis['status']}\n")

    if analysis.get("key_findings"):
        parts.append("## Key Findings\n")
        for f in analysis["key_findings"]:
            parts.append(f"- {f}")
        parts.append("")

    if analysis.get("people_involved"):
        parts.append(f"## People ({len(analysis['people_involved'])})\n")
        for p in analysis["people_involved"]:
            if isinstance(p, dict):
                parts.append(f"- **{p.get('name', '?')}** — {p.get('role', '')} — {p.get('involvement', '')}")
        parts.append("")

    if analysis.get("timeline"):
        parts.append(f"## Timeline ({len(analysis['timeline'])})\n")
        for event in sorted(analysis["timeline"], key=lambda x: str(x.get("date", ""))):
            if isinstance(event, dict):
                parts.append(f"- **{event.get('date', '?')}** — {event.get('event', '')}")
        parts.append("")

    if analysis.get("action_items"):
        parts.append("## Action Items\n")
        for item in analysis["action_items"]:
            parts.append(f"- [ ] {item}")
        parts.append("")

    if analysis.get("risks_and_issues"):
        parts.append("## Risks & Issues\n")
        for risk in analysis["risks_and_issues"]:
            parts.append(f"- ⚠️ {risk}")
        parts.append("")

    if analysis.get("next_steps"):
        parts.append("## Next Steps\n")
        for step in analysis["next_steps"]:
            parts.append(f"1. {step}")
        parts.append("")

    if analysis.get("relationships"):
        parts.append(f"## Relationships ({len(analysis['relationships'])})\n")
        for r in analysis["relationships"]:
            if isinstance(r, dict):
                parts.append(f"- {r.get('source', '?')} → *{r.get('type', 'related_to')}* → {r.get('target', '?')}")
        parts.append("")

    # Document index
    parts.append(f"## Documents in this Folder ({len(docs)})\n")
    for d in docs:
        parts.append(f"- **{d['title']}** ({d['category']})")
    parts.append("")

    if analysis.get("tags"):
        parts.append("## Tags\n")
        parts.append(" ".join(f"`{t}`" for t in analysis["tags"]))
        parts.append("")

    return "\n".join(parts)

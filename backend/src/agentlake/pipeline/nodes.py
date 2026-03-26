"""Processing graph nodes — each function is a node in the LangGraph pipeline.

Each node receives the full PipelineState and returns a partial dict
of state updates. LangGraph merges the updates into the state.

Convention:
    - Nodes are pure-ish functions: read state, do work, return updates.
    - Side effects (DB writes, MinIO reads) are allowed but isolated.
    - All LLM calls go through LLMClient → LLM Gateway (invariant #1).
    - Every node publishes SSE progress events via Redis.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.adapters.base import ExtractedContent
from agentlake.adapters.registry import AdapterRegistry
from agentlake.config import Settings, get_settings
from agentlake.core.database import _get_session_factory
from agentlake.models.diff_log import DiffLog, DiffType
from agentlake.models.document import Citation, DocumentChunk, ProcessedDocument
from agentlake.models.file import File, FileStatus
from agentlake.pipeline.state import PipelineState
from agentlake.prompts.classify_ontology import build_classify_prompt
from agentlake.prompts.extract_entities import build_extract_entities_prompt
from agentlake.prompts.extract_relationships import build_extract_relationships_prompt
from agentlake.prompts.summarize_chunk import build_summarize_chunk_prompt
from agentlake.prompts.summarize_document import build_summarize_document_prompt
from agentlake.services.chunker import Chunk, SemanticChunker
from agentlake.services.llm_client import LLMClient
from agentlake.services.storage import StorageService

logger = structlog.get_logger(__name__)

# ── Shared helpers ────────────────────────────────────────────────────────


def _publish_event(file_id: str, stage: str, progress: int, message: str = "") -> None:
    """Publish SSE event to Redis for real-time progress tracking."""
    try:
        import redis

        settings = get_settings()
        r = redis.from_url(settings.REDIS_URL)
        payload = json.dumps({
            "stage": stage,
            "progress": progress,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        r.publish(f"processing:{file_id}", payload)
        r.close()
    except Exception:
        pass  # SSE is best-effort


def _parse_yaml_or_json(text: str) -> Any:
    """Extract YAML or JSON from LLM response text.

    Handles reasoning models that embed JSON inside thinking text.
    Tries multiple extraction strategies in order of reliability.
    """
    if not text or not text.strip():
        return {}

    # Strategy 0: Direct JSON parse (works for GPT-5.4 which returns clean JSON)
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Strategy 1: Find a code block
    block_match = re.search(r"```(?:ya?ml|json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if block_match:
        try:
            return json.loads(block_match.group(1))
        except (json.JSONDecodeError, ValueError):
            try:
                result = yaml.safe_load(block_match.group(1))
                if isinstance(result, (dict, list)):
                    return result
            except yaml.YAMLError:
                pass

    # Strategy 2: Find balanced JSON arrays — scan for [ and find matching ]
    for match in re.finditer(r'\[', text):
        start = match.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            return parsed
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break

    # Strategy 3: Find balanced JSON objects
    for match in re.finditer(r'\{', text):
        start = match.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict) and len(parsed) > 0:
                            return parsed
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break

    # Strategy 4: Try the whole text as YAML
    try:
        result = yaml.safe_load(text)
        if isinstance(result, (dict, list)):
            return result
    except yaml.YAMLError:
        pass

    return {}


def _strip_reasoning(text: str) -> str:
    """Strip chain-of-thought reasoning from LLM output.

    Reasoning models (e.g. Nemotron Super) prefix their actual answer with
    thinking like "Okay, let's tackle this..." or "Let me think about...".
    This function extracts the actual answer.
    """
    if not text:
        return text

    # Pattern 1: If there's a </think> tag, take everything after it
    if "</think>" in text:
        return text.split("</think>")[-1].strip()

    # Pattern 2: Look for the actual answer after reasoning preamble
    # Reasoning usually starts with "Okay," "Let me," "First," "I need to," etc.
    # and the answer often starts after a double newline or after reasoning ends
    reasoning_prefixes = [
        "okay,", "ok,", "let me", "let's", "first,", "i need to",
        "i should", "the user", "alright", "so,", "hmm", "well,",
    ]
    lower = text.lower().strip()
    starts_with_reasoning = any(lower.startswith(p) for p in reasoning_prefixes)

    if starts_with_reasoning:
        # Try to find where the actual answer starts
        # Look for a paragraph break after the reasoning
        lines = text.split("\n")
        # Skip lines that look like reasoning (usually longer, conversational)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            stripped_lower = stripped.lower()
            if not any(stripped_lower.startswith(p) for p in reasoning_prefixes) and \
               "user" not in stripped_lower[:30] and \
               "think" not in stripped_lower[:30] and \
               "need to" not in stripped_lower[:20] and \
               "should" not in stripped_lower[:20] and \
               len(stripped) < 200:  # titles/short answers are short
                return stripped

        # If we couldn't find a clean break, try taking the last short line
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and len(stripped) < 150 and not any(stripped.lower().startswith(p) for p in reasoning_prefixes):
                return stripped

    return text.strip()


def _get_llm_client() -> LLMClient:
    """Create an LLMClient instance from settings."""
    settings = get_settings()
    return LLMClient(
        gateway_url=settings.LLM_GATEWAY_URL,
        service_token=settings.LLM_GATEWAY_SERVICE_TOKEN,
        service_name="distiller",
    )


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH NODES
# ═══════════════════════════════════════════════════════════════════════════


async def extract_node(state: PipelineState) -> dict:
    """Stage 1: Download file from MinIO and extract text via adapter.

    Reads: file_id
    Writes: file_bytes, filename, content_type, storage_key, extracted
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="extract")
    log.info("extract_started")
    _publish_event(file_id, "extracting", 5)

    settings = get_settings()
    storage = StorageService(settings)
    session_factory = _get_session_factory(settings)

    async with session_factory() as db:
        stmt = select(File).where(File.id == uuid.UUID(file_id))
        result = await db.execute(stmt)
        file = result.scalar_one_or_none()
        if file is None:
            raise ValueError(f"File not found: {file_id}")

        file.status = FileStatus.PROCESSING.value
        file.processing_started_at = datetime.now(timezone.utc)
        await db.commit()

    file_bytes = await storage.download_file(file.storage_key)

    registry = AdapterRegistry()
    registry.auto_discover()
    adapter = registry.get_adapter(file.filename, file.content_type)
    extracted = adapter.extract(file_bytes, file.filename)

    log.info("extract_complete", blocks=len(extracted.text_blocks))
    _publish_event(file_id, "extracting", 15, f"Extracted {len(extracted.text_blocks)} blocks")

    return {
        "file_bytes": file_bytes,
        "filename": file.filename,
        "content_type": file.content_type,
        "storage_key": file.storage_key,
        "extracted": extracted,
        "current_stage": "extracting",
        "progress": 15,
    }


async def chunk_node(state: PipelineState) -> dict:
    """Stage 2: Split extracted content into semantic chunks.

    Reads: extracted, file_id
    Writes: chunks
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="chunk")
    log.info("chunk_started")
    _publish_event(file_id, "chunking", 20)

    settings = get_settings()
    chunker = SemanticChunker(
        max_tokens=settings.CHUNK_MAX_TOKENS,
        overlap_tokens=settings.CHUNK_OVERLAP_TOKENS,
    )
    chunks = chunker.chunk(state["extracted"])

    if not chunks:
        raise ValueError(f"No chunks produced from {state['filename']}")

    log.info("chunk_complete", count=len(chunks))
    _publish_event(file_id, "chunking", 25, f"{len(chunks)} chunks")

    return {
        "chunks": chunks,
        "current_stage": "chunking",
        "progress": 25,
    }


async def full_document_analysis_node(state: PipelineState) -> dict:
    """Single-pass full-document analysis using GPT-5.4's 1M context.

    Sends the ENTIRE raw document to the LLM and extracts everything in one call:
    title, summary, category, sections, entities, people, relationships,
    tags, dates, metrics, cross-references, and key quotes.

    Replaces: summarize_chunks + summarize_document + classify +
              extract_entities + extract_relationships + generate_tags + detect_people

    Reads: extracted, filename, file_id
    Writes: document_title, document_summary, category, sections, entities,
            people, relationships, tags, dates, metrics, cross_references,
            key_quotes, classification
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="full_analysis")
    log.info("full_document_analysis_started")
    _publish_event(file_id, "analyzing", 30, "Running full document analysis...")

    from agentlake.prompts.full_document_analysis import build_full_analysis_prompt

    full_text = state["extracted"].full_text
    filename = state["filename"]
    metadata = state["extracted"].metadata

    log.info("sending_to_llm", text_length=len(full_text), filename=filename)

    llm = _get_llm_client()

    try:
        messages = build_full_analysis_prompt(full_text, filename, metadata)
        result = await llm.complete(
            messages=messages,
            purpose="summarize",
            max_tokens=16000,
            temperature=0.1,
        )
        tokens = result.total_tokens
        raw_content = _strip_reasoning(result.content)
        analysis = _parse_yaml_or_json(raw_content)

        if not isinstance(analysis, dict) or not analysis.get("title"):
            log.warning("analysis_parse_failed_retrying", raw_length=len(raw_content))
            # Retry with explicit JSON instruction
            result2 = await llm.complete(
                messages=messages + [
                    {"role": "assistant", "content": raw_content[:500]},
                    {"role": "user", "content": "Please return ONLY a valid JSON object. No markdown, no code blocks, no commentary."},
                ],
                purpose="summarize",
                max_tokens=16000,
                temperature=0.0,
            )
            tokens += result2.total_tokens
            analysis = _parse_yaml_or_json(_strip_reasoning(result2.content))

    except Exception as e:
        log.error("full_analysis_failed", error=str(e))
        analysis = {}
        tokens = 0

    await llm.close()

    # Handle cases where parser returns a list instead of dict
    if isinstance(analysis, list) and len(analysis) > 0 and isinstance(analysis[0], dict):
        analysis = analysis[0]
    if not isinstance(analysis, dict):
        log.warning("analysis_not_dict", type=type(analysis).__name__)
        analysis = {}

    # Extract all fields with safe defaults
    title = analysis.get("title", filename.replace(".md", "").replace("-", " ").title())
    summary = analysis.get("summary", full_text[:500])
    category = "reference"
    raw_cat = analysis.get("category", "reference")
    for valid in ["technical", "business", "operational", "research", "communication", "reference"]:
        if valid in str(raw_cat).lower():
            category = valid
            break

    entities = analysis.get("entities", [])
    if not isinstance(entities, list):
        entities = []

    people = analysis.get("people", [])
    if not isinstance(people, list):
        people = []

    relationships = analysis.get("relationships", [])
    if not isinstance(relationships, list):
        relationships = []

    tags = analysis.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).lower().strip().replace(" ", "-")[:50] for t in tags if isinstance(t, str) and len(str(t).strip()) > 1]
    if category not in tags:
        tags.insert(0, category)

    sections = analysis.get("sections", [])
    dates = analysis.get("dates", [])
    metrics_list = analysis.get("metrics", [])
    cross_refs = analysis.get("cross_references", [])
    key_quotes = analysis.get("key_quotes", [])

    log.info(
        "full_document_analysis_complete",
        title=title[:60],
        category=category,
        entities=len(entities),
        people=len(people),
        relationships=len(relationships),
        tags=len(tags),
        sections=len(sections),
        dates=len(dates if isinstance(dates, list) else []),
        metrics=len(metrics_list if isinstance(metrics_list, list) else []),
        tokens=tokens,
    )

    _publish_event(file_id, "analyzing", 70, f"Extracted {len(entities)} entities, {len(people)} people, {len(relationships)} relationships")

    return {
        "document_title": title,
        "document_summary": summary,
        "category": category,
        "category_confidence": float(analysis.get("category_confidence", analysis.get("confidence", 0.5))),
        "sections": sections if isinstance(sections, list) else [],
        "entities": entities,
        "people": people,
        "relationships": relationships,
        "tags": tags[:25],
        "dates": dates if isinstance(dates, list) else [],
        "metrics": metrics_list if isinstance(metrics_list, list) else [],
        "cross_references": cross_refs if isinstance(cross_refs, list) else [],
        "key_quotes": key_quotes if isinstance(key_quotes, list) else [],
        "classification": analysis,
        "current_stage": "analyzing",
        "progress": 70,
        "llm_calls_made": 1 if tokens > 0 else 0,
        "total_tokens_used": tokens,
    }


# ── Legacy nodes (kept for backward compatibility, no longer used in main graph) ──


async def summarize_chunks_node(state: PipelineState) -> dict:
    """Stage 3a: Summarize each chunk via LLM (parallelized).

    Reads: chunks, filename, file_id
    Writes: chunk_summaries, llm_calls_made, total_tokens_used
    """
    file_id = state["file_id"]
    chunks = state["chunks"]
    filename = state["filename"]
    log = logger.bind(file_id=file_id, stage="summarize_chunks")
    log.info("summarize_chunks_started", count=len(chunks))
    _publish_event(file_id, "summarizing", 30)

    llm = _get_llm_client()
    summaries: list[str] = [""] * len(chunks)
    calls = 0
    tokens = 0

    # Process chunks in parallel batches of 5
    batch_size = 5
    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start : batch_start + batch_size]

        async def _summarize_one(idx: int, chunk: Chunk) -> tuple[int, str, int, int]:
            messages = build_summarize_chunk_prompt(
                chunk.content, filename, chunk.source_locator
            )
            try:
                result = await llm.complete(messages=messages, purpose="summarize")
                return idx, _strip_reasoning(result.content), 1, result.total_tokens
            except Exception as e:
                log.warning("chunk_summarize_failed", idx=idx, error=str(e))
                return idx, chunk.content[:300], 0, 0

        tasks = [
            _summarize_one(batch_start + i, chunk)
            for i, chunk in enumerate(batch)
        ]
        results = await asyncio.gather(*tasks)

        for idx, summary, c, t in results:
            summaries[idx] = summary
            calls += c
            tokens += t

        pct = 30 + int(30 * min(batch_start + batch_size, len(chunks)) / len(chunks))
        _publish_event(file_id, "summarizing", pct, f"Summarized {min(batch_start + batch_size, len(chunks))}/{len(chunks)} chunks")

    await llm.close()
    log.info("summarize_chunks_complete", calls=calls, tokens=tokens)

    return {
        "chunk_summaries": summaries,
        "llm_calls_made": calls,
        "total_tokens_used": tokens,
        "current_stage": "summarizing",
        "progress": 60,
    }


async def summarize_document_node(state: PipelineState) -> dict:
    """Stage 3b: Generate document-level rollup summary.

    Reads: chunk_summaries, filename, file_id
    Writes: document_summary, document_title
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="summarize_document")
    log.info("summarize_document_started")

    llm = _get_llm_client()
    messages = build_summarize_document_prompt(
        state["chunk_summaries"], state["filename"]
    )

    try:
        result = await llm.complete(messages=messages, purpose="summarize")
        summary = _strip_reasoning(result.content)
        tokens = result.total_tokens
    except Exception as e:
        log.warning("document_summarize_failed", error=str(e))
        summary = "\n".join(state["chunk_summaries"][:3])[:500]
        tokens = 0

    # Generate title
    title = state["filename"].replace(".md", "").replace("-", " ").title()
    try:
        title_result = await llm.complete(
            messages=[
                {"role": "system", "content": "Generate a short descriptive title (5-10 words) for this document. Reply with ONLY the title."},
                {"role": "user", "content": summary[:1000]},
            ],
            purpose="summarize",
            max_tokens=30,
            temperature=0.1,
        )
        raw_title = _strip_reasoning(title_result.content)
        if raw_title and len(raw_title.strip()) > 3:
            title = raw_title.strip().strip('"').strip("'").strip("*").strip()[:100]
            tokens += title_result.total_tokens
    except Exception:
        pass

    await llm.close()
    log.info("summarize_document_complete", summary_len=len(summary))

    return {
        "document_summary": summary,
        "document_title": title,
        "llm_calls_made": 2,
        "total_tokens_used": tokens,
    }


async def cite_node(state: PipelineState) -> dict:
    """Generate citation links and assemble markdown body.

    Uses sections from full_document_analysis (if available) or falls back
    to chunk content for building the document body.

    Reads: file_id, chunks, document_summary, document_title, sections, entities, people, key_quotes
    Writes: citations, body_markdown
    """
    file_id = state["file_id"]
    chunks = state["chunks"]
    log = logger.bind(file_id=file_id, stage="cite")
    log.info("cite_started")
    _publish_event(file_id, "citing", 75)

    # Build citations — each chunk links to source
    citations = []
    for i, chunk in enumerate(chunks):
        citations.append({
            "citation_index": i + 1,
            "source_file_id": file_id,
            "chunk_index": i,
            "source_locator": chunk.source_locator,
            "quote_snippet": chunk.content[:150],
        })

    # Build markdown body from analysis sections + chunk citations
    doc_sections = state.get("sections", [])
    summary = state.get("document_summary", "")
    title = state.get("document_title", "")
    people = state.get("people", [])
    entities = state.get("entities", [])
    key_quotes = state.get("key_quotes", [])
    metrics = state.get("metrics", [])

    # Section content from full analysis
    section_parts = []
    for sec in doc_sections:
        if isinstance(sec, dict):
            heading = sec.get("heading", "")
            sec_summary = sec.get("summary", "")
            key_points = sec.get("key_points", [])
            section_md = f"### {heading}\n\n{sec_summary}"
            if key_points and isinstance(key_points, list):
                section_md += "\n\n" + "\n".join(f"- {p}" for p in key_points)
            section_parts.append(section_md)

    # People section
    people_md = ""
    if people:
        people_lines = []
        for p in people:
            if isinstance(p, dict) and p.get("name"):
                line = f"**{p['name']}**"
                if p.get("role"): line += f" — {p['role']}"
                if p.get("organization"): line += f" @ {p['organization']}"
                if p.get("email"): line += f" ({p['email']})"
                if p.get("context"): line += f"\n  {p['context']}"
                people_lines.append(line)
        if people_lines:
            people_md = "\n## People Mentioned\n\n" + "\n\n".join(people_lines)

    # Key quotes section
    quotes_md = ""
    if key_quotes:
        quotes_md = "\n## Key Quotes\n\n" + "\n\n".join(f"> {q}" for q in key_quotes[:10])

    # Citations section
    citations_md = "\n".join(
        f"[{i + 1}](/api/v1/vault/files/{file_id}/download#chunk={i})"
        for i in range(len(chunks))
    )

    sections_md = "\n\n".join(section_parts) if section_parts else ""

    body_markdown = f"""# {title}

{summary}

---

{sections_md}
{people_md}
{quotes_md}

---

## Citations

{citations_md}
"""
    log.info("cite_complete", citation_count=len(citations), sections=len(section_parts))
    _publish_event(file_id, "citing", 78)

    return {
        "citations": citations,
        "body_markdown": body_markdown,
        "current_stage": "citing",
        "progress": 78,
    }


async def classify_node(state: PipelineState) -> dict:
    """Stage 5a: Classify document into ontology category.

    Reads: document_summary, chunk_summaries, file_id
    Writes: category, classification
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="classify")
    log.info("classify_started")
    _publish_event(file_id, "ontology_mapping", 70)

    llm = _get_llm_client()
    messages = build_classify_prompt(
        state["document_summary"], state["chunk_summaries"]
    )

    category = "reference"
    classification = {}
    try:
        result = await llm.complete(messages=messages, purpose="classify")
        classification = _parse_yaml_or_json(result.content)
        if isinstance(classification, dict):
            raw_cat = classification.get("category", "reference")
            for valid in ["technical", "business", "operational", "research", "communication", "reference"]:
                if valid in str(raw_cat).lower():
                    category = valid
                    break
    except Exception as e:
        log.warning("classify_failed", error=str(e))

    await llm.close()
    log.info("classify_complete", category=category)
    _publish_event(file_id, "ontology_mapping", 75)

    return {
        "category": category,
        "classification": classification,
        "llm_calls_made": 1,
    }


async def extract_entities_node(state: PipelineState) -> dict:
    """Stage 5b: Extract named entities from document.

    Reads: document_summary, file_id
    Writes: entities
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="extract_entities")
    log.info("extract_entities_started")

    llm = _get_llm_client()
    messages = build_extract_entities_prompt(state["document_summary"])

    entities = []
    try:
        result = await llm.complete(messages=messages, purpose="extract_entities")
        parsed = _parse_yaml_or_json(result.content)
        if isinstance(parsed, list):
            entities = [
                {"name": e.get("name", ""), "type": e.get("type", "unknown")}
                for e in parsed
                if isinstance(e, dict) and e.get("name")
            ]
    except Exception as e:
        log.warning("entity_extraction_failed", error=str(e))

    await llm.close()
    log.info("extract_entities_complete", count=len(entities))

    return {
        "entities": entities,
        "llm_calls_made": 1,
    }


async def extract_relationships_node(state: PipelineState) -> dict:
    """Stage 5c: Extract relationships between entities.

    Reads: entities, document_summary, file_id
    Writes: relationships

    Only runs if entities were found.
    """
    file_id = state["file_id"]
    entities = state.get("entities", [])
    log = logger.bind(file_id=file_id, stage="extract_relationships")

    if len(entities) < 2:
        log.info("extract_relationships_skipped", reason="too_few_entities")
        return {"relationships": []}

    log.info("extract_relationships_started", entity_count=len(entities))
    llm = _get_llm_client()
    messages = build_extract_relationships_prompt(entities, state["document_summary"])

    relationships = []
    try:
        result = await llm.complete(messages=messages, purpose="extract_relationships")
        parsed = _parse_yaml_or_json(result.content)
        if isinstance(parsed, list):
            relationships = [
                {
                    "source_entity": r.get("source_entity", ""),
                    "target_entity": r.get("target_entity", ""),
                    "relationship_type": r.get("relationship_type", "related_to"),
                    "description": r.get("description", ""),
                    "confidence": float(r.get("confidence", 0.5)),
                }
                for r in parsed
                if isinstance(r, dict) and r.get("source_entity") and r.get("target_entity")
            ]
    except Exception as e:
        log.warning("relationship_extraction_failed", error=str(e))

    await llm.close()
    log.info("extract_relationships_complete", count=len(relationships))

    return {
        "relationships": relationships,
        "llm_calls_made": 1,
    }


async def generate_tags_node(state: PipelineState) -> dict:
    """Stage 5d: Auto-generate tags for search and discovery.

    Generates tags about document intent, content type, topics,
    and key themes to improve searchability.

    Reads: document_summary, chunk_summaries, filename, category, file_id
    Writes: tags
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="generate_tags")
    log.info("generate_tags_started")

    llm = _get_llm_client()
    summary = state.get("document_summary", "")
    filename = state.get("filename", "")
    category = state.get("category", "reference")

    try:
        result = await llm.complete(
            messages=[
                {"role": "system", "content": """Generate tags for a document to improve searchability.

Return a JSON array of lowercase tag strings (10-20 tags). Include tags for:
- **Intent**: what the document is for (e.g., "decision-record", "status-update", "proposal", "guide", "report", "analysis", "policy", "meeting-notes", "postmortem", "roadmap")
- **Content type**: the format/structure (e.g., "technical-spec", "financial-report", "how-to", "comparison", "checklist")
- **Topics**: key subjects covered (e.g., "kubernetes", "revenue", "hiring", "security", "machine-learning")
- **Audience**: who it's for (e.g., "engineering", "leadership", "all-hands", "investors")
- **Urgency/status**: if applicable (e.g., "action-required", "draft", "archived", "in-progress")
- **Time-relevance**: quarters, years if mentioned (e.g., "q4-2024", "2025-planning")

Return ONLY a JSON array of strings, nothing else."""},
                {"role": "user", "content": f"Filename: {filename}\nCategory: {category}\n\nSummary:\n{summary[:2000]}"},
            ],
            purpose="classify",
            max_tokens=400,
            temperature=0.2,
        )
        tokens = result.total_tokens

        parsed = _parse_yaml_or_json(result.content)
        if isinstance(parsed, list):
            tags = [
                str(t).lower().strip().replace(" ", "-")[:50]
                for t in parsed
                if isinstance(t, str) and len(str(t).strip()) > 1
            ]
        else:
            tags = []

    except Exception as e:
        log.warning("generate_tags_failed", error=str(e))
        tags = []
        tokens = 0

    # Always include the category as a tag
    if category and category not in tags:
        tags.insert(0, category)

    await llm.close()
    log.info("generate_tags_complete", count=len(tags), tags=tags[:5])

    return {
        "tags": tags[:20],  # cap at 20
        "llm_calls_made": 1,
        "total_tokens_used": tokens,
    }


async def detect_people_node(state: PipelineState) -> dict:
    """Stage 5e: Extract people with roles and contact details.

    Looks for names, job titles, email addresses, phone numbers,
    and organizational affiliations mentioned in the document.

    Reads: document_summary, chunk_summaries, file_id
    Writes: people
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="detect_people")
    log.info("detect_people_started")

    llm = _get_llm_client()
    # Use both summary and raw chunk content for better extraction
    summary = state.get("document_summary", "")
    chunk_texts = "\n".join(
        s[:300] for s in state.get("chunk_summaries", [])[:10]
    )

    try:
        result = await llm.complete(
            messages=[
                {"role": "system", "content": """Extract all people mentioned in this document.

For each person, return a JSON object with:
- **name**: full name as mentioned
- **role**: job title or role if mentioned (e.g., "CTO", "VP Engineering", "Lead Developer")
- **organization**: company or team they belong to if mentioned
- **email**: email address if found (null otherwise)
- **phone**: phone number if found (null otherwise)
- **context**: one sentence about what they did or were mentioned for
- **department**: department if mentioned (e.g., "Engineering", "Sales", "Research")

Return a JSON array of person objects. Only include people explicitly named (not generic roles).
Return ONLY valid JSON array, nothing else."""},
                {"role": "user", "content": f"Document content:\n\n{summary[:1500]}\n\n{chunk_texts[:2000]}"},
            ],
            purpose="extract_entities",
            max_tokens=1500,
            temperature=0.1,
        )
        tokens = result.total_tokens

        parsed = _parse_yaml_or_json(result.content)
        people = []
        if isinstance(parsed, list):
            for person in parsed:
                if isinstance(person, dict) and person.get("name"):
                    people.append({
                        "name": str(person["name"]).strip(),
                        "role": person.get("role") or None,
                        "organization": person.get("organization") or None,
                        "email": person.get("email") or None,
                        "phone": person.get("phone") or None,
                        "context": str(person.get("context", ""))[:200],
                        "department": person.get("department") or None,
                    })

    except Exception as e:
        log.warning("detect_people_failed", error=str(e))
        people = []
        tokens = 0

    await llm.close()
    log.info("detect_people_complete", count=len(people))

    return {
        "people": people,
        "llm_calls_made": 1,
        "total_tokens_used": tokens,
    }


async def embed_node(state: PipelineState) -> dict:
    """Stage 6a: Generate embeddings for document and chunks.

    Reads: document_summary, chunks, file_id
    Writes: document_embedding, chunk_embeddings
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="embed")
    log.info("embed_started")
    _publish_event(file_id, "generating_embeddings", 80)

    llm = _get_llm_client()
    doc_embedding = None
    chunk_embeddings: list[list[float]] = []

    try:
        # Document-level embedding
        embeddings = await llm.embed([state["document_summary"]])
        doc_embedding = embeddings[0] if embeddings else None

        # Chunk embeddings in batches
        chunks = state["chunks"]
        batch_size = 20
        for i in range(0, len(chunks), batch_size):
            batch_texts = [c.content[:2000] for c in chunks[i : i + batch_size]]
            batch_embs = await llm.embed(batch_texts)
            chunk_embeddings.extend(batch_embs)
    except Exception as e:
        log.warning("embedding_failed", error=str(e))
        # Continue without embeddings — search will still work via keyword

    await llm.close()
    log.info("embed_complete", doc_has_embedding=doc_embedding is not None, chunk_count=len(chunk_embeddings))
    _publish_event(file_id, "generating_embeddings", 88)

    return {
        "document_embedding": doc_embedding,
        "chunk_embeddings": chunk_embeddings,
    }


async def store_node(state: PipelineState) -> dict:
    """Stage 6b: Persist everything to the database.

    Reads: all state
    Writes: document_id, frontmatter, processing_completed_at
    """
    file_id = state["file_id"]
    log = logger.bind(file_id=file_id, stage="store")
    log.info("store_started")
    _publish_event(file_id, "storing", 90)

    settings = get_settings()
    session_factory = _get_session_factory(settings)

    tags = state.get("tags", [])
    people = state.get("people", [])

    frontmatter = {
        "source_file_id": file_id,
        "title": state.get("document_title", ""),
        "summary": state.get("document_summary", "")[:500],
        "category": state.get("category", "reference"),
        "category_confidence": state.get("category_confidence", 0),
        "entities": state.get("entities", []),
        "people": people,
        "relationships": state.get("relationships", []),
        "tags": tags,
        "sections": state.get("sections", []),
        "dates": state.get("dates", []),
        "metrics": state.get("metrics", []),
        "cross_references": state.get("cross_references", []),
        "key_quotes": state.get("key_quotes", []),
        "processing_version": settings.PROCESSING_VERSION,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "llm_calls_made": state.get("llm_calls_made", 0),
        "total_tokens_used": state.get("total_tokens_used", 0),
    }

    async with session_factory() as db:
        # Create ProcessedDocument
        doc = ProcessedDocument(
            source_file_id=uuid.UUID(file_id),
            title=state.get("document_title", state.get("filename", "")),
            summary=state.get("document_summary", "")[:2000],
            category=state.get("category", "reference"),
            body_markdown=state.get("body_markdown", ""),
            frontmatter=frontmatter,
            entities=state.get("entities", []),
            embedding=state.get("document_embedding"),
            version=1,
            is_current=True,
            processing_version=settings.PROCESSING_VERSION,
        )
        # Set search_vector manually
        db.add(doc)
        await db.flush()

        # Create chunks
        chunks = state.get("chunks", [])
        chunk_summaries = state.get("chunk_summaries", [])
        chunk_embeddings = state.get("chunk_embeddings", [])
        for i, chunk in enumerate(chunks):
            db.add(DocumentChunk(
                document_id=doc.id,
                chunk_index=i,
                content=chunk.content,
                summary=chunk_summaries[i][:2000] if i < len(chunk_summaries) else None,
                embedding=chunk_embeddings[i] if i < len(chunk_embeddings) else None,
                source_locator=chunk.source_locator,
                token_count=chunk.token_count,
                content_hash=chunk.content_hash,
            ))

        # Create citations
        for cit in state.get("citations", []):
            db.add(Citation(
                document_id=doc.id,
                citation_index=cit["citation_index"],
                source_file_id=uuid.UUID(cit["source_file_id"]),
                chunk_index=cit["chunk_index"],
                source_locator=cit["source_locator"],
                quote_snippet=cit.get("quote_snippet"),
            ))

        # Create/attach tags
        from agentlake.models.tag import Tag, FileTag
        for tag_name in tags:
            tag_name = tag_name.lower().strip()[:100]
            if not tag_name:
                continue
            tag_stmt = select(Tag).where(Tag.name == tag_name)
            tag_result = await db.execute(tag_stmt)
            tag_obj = tag_result.scalar_one_or_none()
            if tag_obj is None:
                tag_obj = Tag(name=tag_name, description=f"Auto-generated during processing")
                db.add(tag_obj)
                await db.flush()
            # Attach to file
            existing_ft = await db.execute(
                select(FileTag).where(
                    FileTag.file_id == uuid.UUID(file_id),
                    FileTag.tag_id == tag_obj.id,
                )
            )
            if existing_ft.scalar_one_or_none() is None:
                db.add(FileTag(
                    file_id=uuid.UUID(file_id),
                    tag_id=tag_obj.id,
                    assigned_by="pipeline",
                ))

        # Store people in entities (merge with existing entity list)
        if people:
            merged_entities = list(state.get("entities", []))
            for person in people:
                merged_entities.append({
                    "name": person["name"],
                    "type": "person",
                    "role": person.get("role"),
                    "organization": person.get("organization"),
                    "email": person.get("email"),
                    "phone": person.get("phone"),
                    "department": person.get("department"),
                    "context": person.get("context"),
                })
            doc.entities = merged_entities

        # Create diff log
        db.add(DiffLog(
            document_id=doc.id,
            source_file_id=uuid.UUID(file_id),
            diff_type=DiffType.INITIAL_PROCESSING,
            after_text=state.get("body_markdown", "")[:5000],
            justification="Initial processing via LangGraph pipeline",
            metadata={
                "llm_calls": state.get("llm_calls_made", 0),
                "total_tokens": state.get("total_tokens_used", 0),
                "tags_generated": len(tags),
                "people_detected": len(people),
            },
            created_by="pipeline",
        ))

        # Update file status
        stmt = select(File).where(File.id == uuid.UUID(file_id))
        result = await db.execute(stmt)
        file = result.scalar_one_or_none()
        if file:
            file.status = FileStatus.PROCESSED.value
            file.processing_completed_at = datetime.now(timezone.utc)

        # Update search vector
        from sqlalchemy import text

        await db.execute(text("""
            UPDATE processed_documents SET search_vector =
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(left(body_markdown, 10000), '')), 'C')
            WHERE id = :doc_id
        """), {"doc_id": doc.id})

        await db.commit()
        log.info("store_complete", document_id=str(doc.id), chunks=len(chunks))

    now = datetime.now(timezone.utc).isoformat()
    _publish_event(file_id, "complete", 100, f"Processed: {state.get('document_title', '')}")

    return {
        "document_id": str(doc.id),
        "frontmatter": frontmatter,
        "processing_completed_at": now,
        "current_stage": "complete",
        "progress": 100,
    }


async def handle_error_node(state: PipelineState) -> dict:
    """Error handler — marks file as failed."""
    file_id = state["file_id"]
    error = state.get("error", "Unknown error")
    logger.error("pipeline_failed", file_id=file_id, error=error)
    _publish_event(file_id, "error", 0, error)

    settings = get_settings()
    session_factory = _get_session_factory(settings)
    async with session_factory() as db:
        stmt = select(File).where(File.id == uuid.UUID(file_id))
        result = await db.execute(stmt)
        file = result.scalar_one_or_none()
        if file:
            file.status = FileStatus.FAILED.value
            file.error_message = error[:1000]
            await db.commit()

    return {"current_stage": "error"}

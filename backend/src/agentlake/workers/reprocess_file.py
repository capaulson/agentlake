"""Incremental reprocessing Celery task.

When a file is re-uploaded or reprocessed, only chunks whose content
hash changed are re-summarised and re-embedded.  Unchanged chunks reuse
existing summaries.  This dramatically reduces LLM calls and latency.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from agentlake.adapters.registry import AdapterRegistry
from agentlake.config import get_settings
from agentlake.core.database import _get_session_factory
from agentlake.core.exceptions import AgentLakeError
from agentlake.models.document import Citation, DocumentChunk, ProcessedDocument
from agentlake.models.file import File, FileStatus
from agentlake.prompts.classify_ontology import build_classify_prompt
from agentlake.prompts.extract_entities import build_extract_entities_prompt
from agentlake.prompts.extract_relationships import build_extract_relationships_prompt
from agentlake.prompts.summarize_chunk import build_summarize_chunk_prompt
from agentlake.prompts.summarize_document import build_summarize_document_prompt
from agentlake.services.chunker import Chunk, SemanticChunker
from agentlake.services.diff import DiffService
from agentlake.services.llm_client import LLMClient
from agentlake.services.storage import StorageService
from agentlake.workers.celery_app import celery_app
from agentlake.pipeline.nodes import (
    _publish_event as publish_event,
    _parse_yaml_or_json as parse_yaml_response,
    handle_error_node,
)

logger = structlog.get_logger(__name__)


def generate_citations(file_id: str, chunks: list) -> list[dict]:
    """Generate citation dicts for a list of chunks."""
    return [
        {
            "citation_index": i + 1,
            "source_file_id": file_id,
            "chunk_index": i,
            "source_locator": getattr(c, "source_locator", f"chunk:{i}"),
            "quote_snippet": getattr(c, "content", "")[:150],
        }
        for i, c in enumerate(chunks)
    ]


def assemble_markdown(summary: str, chunk_summaries: list[str], citations: list[dict]) -> str:
    """Assemble final markdown document from summaries and citations."""
    file_id = citations[0]["source_file_id"] if citations else "unknown"
    sections = "\n\n".join(
        f"{s} [{i+1}](/api/v1/vault/files/{file_id}/download#chunk={i})"
        for i, s in enumerate(chunk_summaries)
    )
    cit_md = "\n".join(
        f"[{c['citation_index']}](/api/v1/vault/files/{c['source_file_id']}/download#chunk={c['chunk_index']})"
        for c in citations
    )
    return f"# Summary\n\n{summary}\n\n---\n\n## Content\n\n{sections}\n\n---\n\n## Citations\n\n{cit_md}\n"


def build_frontmatter(file_id: str, filename: str, summary: str, classification: dict, entities: list) -> dict:
    """Build ontology frontmatter dict."""
    category = "reference"
    if isinstance(classification, dict):
        raw = classification.get("category", "reference")
        for valid in ["technical", "business", "operational", "research", "communication", "reference"]:
            if valid in str(raw).lower():
                category = valid
                break
    return {
        "source_file_id": file_id,
        "title": filename,
        "summary": summary[:500],
        "category": category,
        "entities": entities if isinstance(entities, list) else [],
    }


# ── Data Structures ──────────────────────────────────────────────────────────


@dataclass
class ChunkMatch:
    """A matched pair of old and new chunks."""

    old_chunk: DocumentChunk
    new_chunk: Chunk
    similarity: float


@dataclass
class ChunkDelta:
    """Result of comparing old chunks against new chunks.

    Attributes:
        unchanged: Old chunks that match new chunks exactly (reuse everything).
        modified: Pairs of (old_chunk, new_chunk) with similarity above threshold
                  but content changed (re-summarize + re-embed).
        added: New chunks with no match in old set (full pipeline).
        removed: Old chunks with no match in new set (to be dropped).
    """

    unchanged: list[ChunkMatch] = field(default_factory=list)
    modified: list[ChunkMatch] = field(default_factory=list)
    added: list[Chunk] = field(default_factory=list)
    removed: list[DocumentChunk] = field(default_factory=list)

    @property
    def change_ratio(self) -> float:
        """Fraction of chunks that changed (modified + added + removed)."""
        total = (
            len(self.unchanged)
            + len(self.modified)
            + len(self.added)
            + len(self.removed)
        )
        if total == 0:
            return 0.0
        changed = len(self.modified) + len(self.added) + len(self.removed)
        return changed / total

    def to_metadata(self) -> dict:
        """Serialize delta stats for DiffLog metadata."""
        return {
            "unchanged_count": len(self.unchanged),
            "modified_count": len(self.modified),
            "added_count": len(self.added),
            "removed_count": len(self.removed),
            "change_ratio": round(self.change_ratio, 4),
        }


# ── Celery Task ──────────────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="reprocess_file",
    queue="high",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def reprocess_file_task(self, file_id: str, mode: str = "incremental") -> dict:
    """Celery entry point for file reprocessing.

    Args:
        file_id: UUID string of the file to reprocess.
        mode: "incremental" (default) or "full".

    Returns:
        Dict with reprocessing result metadata.
    """
    try:
        result = asyncio.run(_reprocess_file(file_id, mode))
        return result
    except AgentLakeError:
        raise
    except Exception as exc:
        logger.exception(
            "reprocess_file_unhandled_error",
            file_id=file_id,
            mode=mode,
            error=str(exc),
        )
        try:
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            asyncio.run(handle_error_node({"file_id": file_id, "error": str(exc)}))
            raise


# ── Main Reprocessing Logic ──────────────────────────────────────────────────


async def _reprocess_file(file_id: str, mode: str) -> dict:
    """Execute reprocessing pipeline.

    Args:
        file_id: UUID string of the file.
        mode: "incremental" or "full".

    Returns:
        Dict with reprocessing result metadata.
    """
    log = logger.bind(file_id=file_id, mode=mode)
    log.info("reprocess_file_started")

    if mode == "full":
        log.info("full_reprocess_delegating")
        from agentlake.pipeline.graph import processing_graph
        result = await processing_graph.ainvoke({"file_id": file_id, "mode": "full", "llm_calls_made": 0, "total_tokens_used": 0})
        return result

    # ── INCREMENTAL MODE ─────────────────────────────────────────────────
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    storage = StorageService(settings)
    registry = AdapterRegistry()
    registry.auto_discover()

    async with LLMClient(
        gateway_url=settings.LLM_GATEWAY_URL,
        service_token=settings.LLM_GATEWAY_SERVICE_TOKEN,
        service_name="distiller",
    ) as llm_client:
        async with session_factory() as db:
            try:
                # Load file
                stmt = select(File).where(File.id == uuid.UUID(file_id))
                result = await db.execute(stmt)
                file = result.scalar_one_or_none()
                if file is None:
                    raise AgentLakeError(f"File not found: {file_id}")

                # Load existing current document
                doc_stmt = (
                    select(ProcessedDocument)
                    .where(ProcessedDocument.source_file_id == uuid.UUID(file_id))
                    .where(ProcessedDocument.is_current.is_(True))
                    .order_by(ProcessedDocument.version.desc())
                )
                doc_result = await db.execute(doc_stmt)
                existing_doc = doc_result.scalar_one_or_none()

                if existing_doc is None:
                    log.info("no_existing_doc_falling_back_to_full")
                    from agentlake.pipeline.graph import processing_graph
                    result = await processing_graph.ainvoke({"file_id": file_id, "mode": "full", "llm_calls_made": 0, "total_tokens_used": 0})
                    return result

                # Update file status
                file.status = FileStatus.PROCESSING.value
                file.processing_started_at = datetime.now(timezone.utc)
                await db.flush()
                publish_event(file_id, "extracting", progress=5)

                # Step 1: Extract + chunk (always, cheap)
                file_bytes = await storage.download_file(file.storage_key)
                adapter = registry.get_adapter(file.filename, file.content_type)
                if adapter is None:
                    raise AgentLakeError(
                        f"No adapter for {file.filename} ({file.content_type})"
                    )
                extracted = adapter.extract(file_bytes, file.filename)
                publish_event(file_id, "extracting", progress=15)

                chunker = SemanticChunker(
                    max_tokens=settings.CHUNK_MAX_TOKENS,
                    overlap_tokens=settings.CHUNK_OVERLAP_TOKENS,
                )
                new_chunks = chunker.chunk(extracted)
                if not new_chunks:
                    raise AgentLakeError(
                        f"No chunks produced from {file.filename}"
                    )
                publish_event(file_id, "chunking", progress=25)

                # Step 2: Load existing chunks
                old_chunks_stmt = (
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == existing_doc.id)
                    .order_by(DocumentChunk.chunk_index)
                )
                old_chunks_result = await db.execute(old_chunks_stmt)
                old_chunks = list(old_chunks_result.scalars().all())

                # Step 3: Compare
                delta = compute_chunk_delta(
                    old_chunks,
                    new_chunks,
                    threshold=settings.INCREMENTAL_SIMILARITY_THRESHOLD,
                )
                log.info(
                    "chunk_delta_computed",
                    unchanged=len(delta.unchanged),
                    modified=len(delta.modified),
                    added=len(delta.added),
                    removed=len(delta.removed),
                    change_ratio=delta.change_ratio,
                )

                # If nothing changed, skip reprocessing
                if not delta.modified and not delta.added and not delta.removed:
                    log.info("no_changes_detected_skipping")
                    file.status = FileStatus.PROCESSED.value
                    file.processing_completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    publish_event(file_id, "complete", progress=100)
                    return {
                        "document_id": str(existing_doc.id),
                        "file_id": file_id,
                        "mode": "incremental",
                        "skipped": True,
                        "reason": "no_changes",
                    }

                publish_event(file_id, "summarizing", progress=30)

                # Step 4-6: Process each category
                chunk_summaries: list[str] = []
                chunk_embeddings: list[list[float]] = []
                final_chunks: list[Chunk] = []

                # Unchanged: reuse existing summaries + embeddings
                for match in delta.unchanged:
                    final_chunks.append(match.new_chunk)
                    chunk_summaries.append(match.old_chunk.summary or "")
                    chunk_embeddings.append(
                        match.old_chunk.embedding or []
                    )

                # Modified: re-summarize + re-embed
                for i, match in enumerate(delta.modified):
                    final_chunks.append(match.new_chunk)
                    messages = build_summarize_chunk_prompt(
                        match.new_chunk.content,
                        file.original_filename,
                        match.new_chunk.source_locator,
                    )
                    summary_result = await llm_client.complete(
                        messages=messages,
                        purpose="summarize",
                        temperature=0.3,
                    )
                    chunk_summaries.append(summary_result.content)

                    emb = await llm_client.embed([match.new_chunk.content])
                    chunk_embeddings.append(emb[0] if emb else [])

                    progress = 30 + int(
                        30
                        * (i + 1)
                        / max(len(delta.modified) + len(delta.added), 1)
                    )
                    publish_event(file_id, "summarizing", progress=progress)

                # Added: full summarize + embed
                for i, chunk in enumerate(delta.added):
                    final_chunks.append(chunk)
                    messages = build_summarize_chunk_prompt(
                        chunk.content,
                        file.original_filename,
                        chunk.source_locator,
                    )
                    summary_result = await llm_client.complete(
                        messages=messages,
                        purpose="summarize",
                        temperature=0.3,
                    )
                    chunk_summaries.append(summary_result.content)

                    emb = await llm_client.embed([chunk.content])
                    chunk_embeddings.append(emb[0] if emb else [])

                    progress = 30 + int(
                        30
                        * (len(delta.modified) + i + 1)
                        / max(len(delta.modified) + len(delta.added), 1)
                    )
                    publish_event(file_id, "summarizing", progress=progress)

                # Sort by original chunk index
                ordered = sorted(
                    zip(final_chunks, chunk_summaries, chunk_embeddings),
                    key=lambda x: x[0].chunk_index,
                )
                final_chunks = [o[0] for o in ordered]
                chunk_summaries = [o[1] for o in ordered]
                chunk_embeddings = [o[2] for o in ordered]

                # Re-do document-level rollup summary
                doc_summary_messages = build_summarize_document_prompt(
                    chunk_summaries, file.original_filename
                )
                doc_summary_result = await llm_client.complete(
                    messages=doc_summary_messages,
                    purpose="summarize",
                    temperature=0.3,
                )
                doc_summary = doc_summary_result.content
                publish_event(file_id, "citing", progress=65)

                # Re-cite
                citations = generate_citations(file_id, final_chunks)
                publish_event(file_id, "ontology_mapping", progress=70)

                # Step 9: Re-classify if >threshold% chunks changed
                reclassify = delta.change_ratio >= settings.INCREMENTAL_RECLASSIFY_THRESHOLD
                if reclassify:
                    log.info(
                        "reclassifying",
                        change_ratio=delta.change_ratio,
                    )
                    classify_messages = build_classify_prompt(
                        doc_summary, chunk_summaries
                    )
                    classification_result = await llm_client.complete(
                        messages=classify_messages,
                        purpose="classify",
                        temperature=0.2,
                    )
                    parsed_classification = parse_yaml_response(
                        classification_result.content
                    )
                    if not isinstance(parsed_classification, dict):
                        parsed_classification = existing_doc.frontmatter
                else:
                    parsed_classification = existing_doc.frontmatter

                # Re-extract entities
                entity_messages = build_extract_entities_prompt(doc_summary)
                entities_result = await llm_client.complete(
                    messages=entity_messages,
                    purpose="extract_entities",
                    temperature=0.2,
                )
                entities = parse_yaml_response(entities_result.content)
                if not isinstance(entities, list):
                    entities = existing_doc.entities if isinstance(existing_doc.entities, list) else []

                # Relationships
                relationships: list[dict] = []
                if entities:
                    rel_messages = build_extract_relationships_prompt(
                        entities, doc_summary
                    )
                    rel_result = await llm_client.complete(
                        messages=rel_messages,
                        purpose="extract_relationships",
                        temperature=0.2,
                    )
                    relationships = parse_yaml_response(rel_result.content)
                    if not isinstance(relationships, list):
                        relationships = []

                publish_event(file_id, "generating_embeddings", progress=85)

                # Generate document-level embedding
                doc_embedding = await llm_client.embed([doc_summary])

                # Step 10: Assemble + store with new version
                body_markdown = assemble_markdown(
                    doc_summary, chunk_summaries, citations
                )
                frontmatter = build_frontmatter(
                    file_id,
                    file.original_filename,
                    doc_summary,
                    parsed_classification,
                    entities,
                )

                # Mark old document as not current
                old_body = existing_doc.body_markdown
                existing_doc.is_current = False
                await db.flush()

                # Determine title
                title = parsed_classification.get("title") or file.original_filename
                if len(title) > 512:
                    title = title[:509] + "..."

                # Create new version
                new_document = ProcessedDocument(
                    source_file_id=uuid.UUID(file_id),
                    title=title,
                    summary=doc_summary,
                    category=parsed_classification.get(
                        "category", existing_doc.category
                    ),
                    body_markdown=body_markdown,
                    frontmatter=frontmatter,
                    entities=entities,
                    embedding=doc_embedding[0] if doc_embedding else None,
                    version=existing_doc.version + 1,
                    is_current=True,
                    processing_version=settings.PROCESSING_VERSION,
                )
                db.add(new_document)
                await db.flush()

                # Create new chunks
                for i, (chunk, summary, emb) in enumerate(
                    zip(final_chunks, chunk_summaries, chunk_embeddings)
                ):
                    db_chunk = DocumentChunk(
                        document_id=new_document.id,
                        chunk_index=i,
                        content=chunk.content,
                        summary=summary,
                        embedding=emb if emb else None,
                        source_locator=chunk.source_locator,
                        token_count=chunk.token_count,
                        content_hash=chunk.content_hash,
                    )
                    db.add(db_chunk)

                # Create new citations
                for cit in citations:
                    db_citation = Citation(
                        document_id=new_document.id,
                        citation_index=cit["citation_index"],
                        source_file_id=uuid.UUID(cit["source_file_id"]),
                        chunk_index=cit["chunk_index"],
                        source_locator=cit["source_locator"],
                        quote_snippet=cit.get("quote_snippet"),
                    )
                    db.add(db_citation)

                # Step 11: DiffLog with delta metadata
                diff_service = DiffService(db)
                await diff_service.create_reprocess_diff(
                    document_id=new_document.id,
                    source_file_id=uuid.UUID(file_id),
                    before_text=old_body,
                    after_text=body_markdown,
                    metadata=delta.to_metadata(),
                    justification=(
                        f"Incremental reprocessing: {len(delta.modified)} modified, "
                        f"{len(delta.added)} added, {len(delta.removed)} removed chunks"
                    ),
                )

                # Update file status
                file.status = FileStatus.PROCESSED.value
                file.processing_completed_at = datetime.now(timezone.utc)

                await db.commit()
                publish_event(file_id, "complete", progress=100)

                log.info(
                    "reprocess_file_complete",
                    document_id=str(new_document.id),
                    version=new_document.version,
                    delta=delta.to_metadata(),
                )

                return {
                    "document_id": str(new_document.id),
                    "file_id": file_id,
                    "mode": "incremental",
                    "version": new_document.version,
                    "delta": delta.to_metadata(),
                    "reclassified": reclassify,
                }

            except Exception as exc:
                await db.rollback()
                log.exception("reprocess_file_error", error=str(exc))
                try:
                    file.status = FileStatus.FAILED.value
                    file.error_message = str(exc)[:2000]
                    await db.commit()
                except Exception:
                    log.exception("mark_file_failed_error")
                raise


# ── Chunk Comparison ─────────────────────────────────────────────────────────


def compute_chunk_delta(
    old_chunks: list[DocumentChunk],
    new_chunks: list[Chunk],
    threshold: float = 0.85,
) -> ChunkDelta:
    """Compare old and new chunk sets to determine what changed.

    Uses content hash for exact match detection, then falls back to
    token-level Jaccard similarity for fuzzy matching.

    Args:
        old_chunks: Existing document chunks from the database.
        new_chunks: Newly produced chunks from re-extraction.
        threshold: Similarity threshold above which a chunk is considered
                   "modified" rather than "added"/"removed".

    Returns:
        ChunkDelta describing what changed.
    """
    delta = ChunkDelta()

    # Build hash lookup for exact matches
    old_by_hash: dict[str, DocumentChunk] = {
        c.content_hash: c for c in old_chunks
    }
    new_by_hash: dict[str, Chunk] = {c.content_hash: c for c in new_chunks}

    # Track which chunks have been matched
    matched_old: set[str] = set()  # content_hash
    matched_new: set[str] = set()  # content_hash

    # Pass 1: Exact hash matches (unchanged)
    for new_hash, new_chunk in new_by_hash.items():
        if new_hash in old_by_hash:
            delta.unchanged.append(
                ChunkMatch(
                    old_chunk=old_by_hash[new_hash],
                    new_chunk=new_chunk,
                    similarity=1.0,
                )
            )
            matched_old.add(new_hash)
            matched_new.add(new_hash)

    # Collect unmatched chunks
    unmatched_old = [c for c in old_chunks if c.content_hash not in matched_old]
    unmatched_new = [c for c in new_chunks if c.content_hash not in matched_new]

    # Pass 2: Fuzzy matching via Jaccard similarity
    used_old_indices: set[int] = set()
    for new_chunk in unmatched_new:
        best_sim = 0.0
        best_idx = -1
        best_old: DocumentChunk | None = None

        for idx, old_chunk in enumerate(unmatched_old):
            if idx in used_old_indices:
                continue
            sim = jaccard_similarity(old_chunk.content, new_chunk.content)
            if sim > best_sim:
                best_sim = sim
                best_idx = idx
                best_old = old_chunk

        if best_sim >= threshold and best_old is not None:
            delta.modified.append(
                ChunkMatch(
                    old_chunk=best_old,
                    new_chunk=new_chunk,
                    similarity=best_sim,
                )
            )
            used_old_indices.add(best_idx)
        else:
            delta.added.append(new_chunk)

    # Any unmatched old chunks are removed
    for idx, old_chunk in enumerate(unmatched_old):
        if idx not in used_old_indices:
            delta.removed.append(old_chunk)

    return delta


def jaccard_similarity(text1: str, text2: str) -> float:
    """Compute token-level Jaccard similarity between two texts.

    Args:
        text1: First text.
        text2: Second text.

    Returns:
        Float between 0.0 (no overlap) and 1.0 (identical token sets).
    """
    if not text1 and not text2:
        return 1.0
    if not text1 or not text2:
        return 0.0

    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())

    if not tokens1 and not tokens2:
        return 1.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    return len(intersection) / len(union) if union else 0.0

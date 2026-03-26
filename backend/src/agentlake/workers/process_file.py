"""Celery task that runs the LangGraph document processing pipeline.

The Celery task is the entry point — it kicks off the LangGraph StateGraph
which handles the actual multi-stage agentic processing with:
    - Parallel fan-out (classify + entity extraction run simultaneously)
    - Conditional branching (skip relationship extraction if < 2 entities)
    - State checkpointing between nodes
    - Structured error handling per-node

Architecture:
    Upload API → Celery Queue → process_file_task → LangGraph Pipeline
                                                      ├── extract
                                                      ├── chunk
                                                      ├── summarize_chunks (parallel batches)
                                                      ├── summarize_document
                                                      ├── cite
                                                      ├── classify ──────┐
                                                      ├── extract_entities┤ (parallel)
                                                      ├── extract_relationships? (conditional)
                                                      ├── embed
                                                      └── store → END
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import structlog

from agentlake.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="process_file",
    queue="default",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def process_file_task(self, file_id: str) -> dict:
    """Celery entry point — runs the LangGraph processing pipeline.

    Args:
        file_id: UUID string of the file to process.

    Returns:
        Dict with document_id, chunk_count, and processing metadata.
    """
    log = logger.bind(file_id=file_id, task_id=self.request.id)
    log.info("process_file_task_started")

    try:
        result = asyncio.run(_run_pipeline(file_id))
        log.info(
            "process_file_task_complete",
            document_id=result.get("document_id"),
            llm_calls=result.get("llm_calls_made", 0),
            tokens=result.get("total_tokens_used", 0),
        )
        return result
    except Exception as exc:
        log.exception("process_file_task_failed", error=str(exc))
        try:
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            asyncio.run(_mark_failed(file_id, str(exc)))
            raise


async def _run_pipeline(file_id: str) -> dict:
    """Execute the LangGraph processing graph."""
    from agentlake.pipeline.graph import processing_graph

    initial_state = {
        "file_id": file_id,
        "mode": "full",
        "current_stage": "pending",
        "progress": 0,
        "error": None,
        "llm_calls_made": 0,
        "total_tokens_used": 0,
        "processing_started_at": datetime.now(timezone.utc).isoformat(),
    }

    # Run the graph
    final_state = await processing_graph.ainvoke(initial_state)

    return {
        "file_id": file_id,
        "document_id": final_state.get("document_id"),
        "document_title": final_state.get("document_title"),
        "category": final_state.get("category"),
        "chunk_count": len(final_state.get("chunks", [])),
        "entity_count": len(final_state.get("entities", [])),
        "relationship_count": len(final_state.get("relationships", [])),
        "llm_calls_made": final_state.get("llm_calls_made", 0),
        "total_tokens_used": final_state.get("total_tokens_used", 0),
        "processing_completed_at": final_state.get("processing_completed_at"),
    }


async def _mark_failed(file_id: str, error: str) -> None:
    """Mark a file as failed after max retries exceeded."""
    from agentlake.pipeline.nodes import handle_error_node

    await handle_error_node({"file_id": file_id, "error": error})

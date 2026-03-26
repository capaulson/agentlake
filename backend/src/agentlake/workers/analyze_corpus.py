"""Celery task for cross-document analysis via LangGraph.

Triggers:
    - Automatically after every Nth document is processed
    - On-demand via API: POST /api/v1/admin/analyze
    - Scheduled via Celery Beat
"""

from __future__ import annotations

import asyncio

import structlog

from agentlake.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="analyze_corpus",
    queue="low",
    max_retries=1,
    default_retry_delay=120,
    acks_late=True,
    time_limit=600,  # 10 min max
)
def analyze_corpus_task(
    self,
    scope: str = "all",
    max_documents: int = 50,
    source_document_id: str | None = None,
) -> dict:
    """Run cross-document analysis pipeline.

    Args:
        scope: "all", "recent", "category:technical", "entity:NovaTech"
        max_documents: Maximum documents to analyze.
        source_document_id: If triggered by a specific document upload.

    Returns:
        Dict with analysis results.
    """
    log = logger.bind(scope=scope, max_documents=max_documents, task_id=self.request.id)
    log.info("analyze_corpus_started")

    try:
        result = asyncio.run(_run_analysis(scope, max_documents, source_document_id))
        log.info(
            "analyze_corpus_complete",
            relationships=len(result.get("relationships", [])),
            clusters=len(result.get("clusters", [])),
            insights=len(result.get("insights", [])),
            insight_doc=result.get("insight_document_id"),
        )
        return {
            "scope": scope,
            "documents_analyzed": result.get("document_count", 0),
            "entity_map_size": len(result.get("entity_map", [])),
            "relationships": len(result.get("relationships", [])),
            "clusters": len(result.get("clusters", [])),
            "insights": len(result.get("insights", [])),
            "graph_updates": result.get("graph_updates", 0),
            "insight_document_id": result.get("insight_document_id"),
            "llm_calls": result.get("llm_calls_made", 0),
            "total_tokens": result.get("total_tokens_used", 0),
        }
    except Exception as exc:
        log.exception("analyze_corpus_failed", error=str(exc))
        raise


async def _run_analysis(
    scope: str, max_documents: int, source_document_id: str | None
) -> dict:
    """Execute the cross-document analysis graph."""
    from agentlake.pipeline.cross_document_graph import cross_doc_graph

    initial_state = {
        "scope": scope,
        "max_documents": max_documents,
        "source_document_id": source_document_id,
        "trigger": "post_processing" if source_document_id else "on_demand",
        "llm_calls_made": 0,
        "total_tokens_used": 0,
    }

    return await cross_doc_graph.ainvoke(initial_state)

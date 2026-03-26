"""Celery task for folder-scoped AI analysis."""

from __future__ import annotations

import asyncio

import structlog

from agentlake.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="analyze_folder",
    queue="low",
    max_retries=1,
    default_retry_delay=60,
    acks_late=True,
    time_limit=300,
)
def analyze_folder_task(self, folder_id: str) -> dict:
    """Analyze a folder's contents and generate an AI summary."""
    log = logger.bind(folder_id=folder_id, task_id=self.request.id)
    log.info("analyze_folder_task_started")

    try:
        from agentlake.pipeline.folder_analysis import analyze_folder
        result = asyncio.run(analyze_folder(folder_id))
        log.info("analyze_folder_task_complete", **{k: v for k, v in result.items() if k != "error"})
        return result
    except Exception as exc:
        log.exception("analyze_folder_task_failed", error=str(exc))
        raise

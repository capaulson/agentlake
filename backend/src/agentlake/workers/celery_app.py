"""Celery application for background processing (Distiller workers)."""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from agentlake.config import get_settings

settings = get_settings()

celery_app = Celery("agentlake")

celery_app.conf.update(
    # Broker / backend
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Concurrency
    worker_concurrency=settings.DISTILLER_CONCURRENCY,
    worker_prefetch_multiplier=1,
    # Task execution limits
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=600,  # 10 minute hard limit
    task_soft_time_limit=540,  # 9 minute soft limit
    # Result expiration
    result_expires=86400,  # 24 hours
    # Queues
    task_queues=(
        Queue("high", routing_key="high"),
        Queue("default", routing_key="default"),
        Queue("low", routing_key="low"),
    ),
    task_default_queue="default",
    task_default_routing_key="default",
    # Task routing
    task_routes={
        "process_file": {"queue": "default"},
        "reprocess_file": {"queue": "high"},
        "analyze_corpus": {"queue": "low"},
        "auto_explore": {"queue": "low"},
        "analyze_folder": {"queue": "low"},
    },
    # Retry policy
    task_default_retry_delay=settings.DISTILLER_RETRY_BACKOFF,
    task_max_retries=settings.DISTILLER_MAX_RETRIES,
)

# Import task modules directly so they register with the celery app
import agentlake.workers.process_file  # noqa: F401, E402
import agentlake.workers.reprocess_file  # noqa: F401, E402
import agentlake.workers.analyze_corpus  # noqa: F401, E402
import agentlake.workers.auto_explore  # noqa: F401, E402
import agentlake.workers.analyze_folder  # noqa: F401, E402

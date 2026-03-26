"""Celery task that automatically explores questions the system is curious about.

Picks up follow-up questions from knowledge_memory, runs them through
the agentic search pipeline (which records results back as new knowledge),
and accumulates institutional understanding over time.

This creates a self-reinforcing loop:
    Questions → Knowledge → Follow-ups → Auto-explore → More Knowledge → Deeper Follow-ups

Trigger rules:
    - Runs after every auto-analysis (post 10 questions)
    - Explores up to 5 questions per run
    - Respects daily token budget
    - Prioritizes unexplored questions from the most active themes
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from agentlake.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

MAX_QUESTIONS_PER_RUN = 5
MAX_DAILY_AUTO_TOKENS = 100_000


@celery_app.task(
    bind=True,
    name="auto_explore",
    queue="low",
    max_retries=1,
    default_retry_delay=120,
    acks_late=True,
    time_limit=600,
)
def auto_explore_task(self, max_questions: int = MAX_QUESTIONS_PER_RUN) -> dict:
    """Automatically explore questions the system wants to investigate.

    Picks the highest-priority unexplored follow-up questions and runs
    them through the agentic search pipeline.
    """
    log = logger.bind(task_id=self.request.id)
    log.info("auto_explore_started", max_questions=max_questions)

    try:
        result = asyncio.run(_explore(max_questions))
        log.info("auto_explore_complete", **result)
        return result
    except Exception as exc:
        log.exception("auto_explore_failed", error=str(exc))
        raise


async def _explore(max_questions: int) -> dict:
    """Pick and explore follow-up questions."""
    from sqlalchemy import text

    from agentlake.config import get_settings
    from agentlake.core.database import _get_session_factory
    from agentlake.models.knowledge import KnowledgeMemory
    from agentlake.pipeline.agentic_search import agentic_search_graph

    settings = get_settings()
    session_factory = _get_session_factory(settings)
    log = logger.bind(stage="auto_explore")

    # Read settings from DB
    async with session_factory() as db:
        settings_result = await db.execute(text("SELECT key, value FROM system_settings"))
        db_settings = {row[0]: row[1] for row in settings_result.fetchall()}

    token_limit = int(db_settings.get("auto_explore_max_tokens_per_hour", MAX_DAILY_AUTO_TOKENS))
    enabled = db_settings.get("auto_explore_enabled", "true").lower() == "true"
    max_q = min(max_questions, int(db_settings.get("auto_explore_max_questions_per_run", MAX_QUESTIONS_PER_RUN)))

    if not enabled:
        log.info("auto_explore_disabled")
        return {"explored": 0, "reason": "disabled_by_admin"}

    # Check hourly token budget
    async with session_factory() as db:
        hourly_result = await db.execute(text("""
            SELECT COALESCE(SUM(tokens_used), 0)
            FROM knowledge_memory
            WHERE created_at > now() - interval '1 hour'
        """))
        hourly_tokens = hourly_result.scalar() or 0

        if hourly_tokens >= token_limit:
            log.info("hourly_token_budget_exceeded", hourly_tokens=hourly_tokens, limit=token_limit)
            return {"explored": 0, "reason": "hourly_token_budget_exceeded", "hourly_tokens": hourly_tokens, "limit": token_limit}

        # Get unexplored follow-up questions, prioritized by:
        # 1. Questions from themes with the most activity
        # 2. Questions generated most recently
        # 3. Avoid duplicates of questions already asked
        result = await db.execute(text("""
            WITH follow_ups AS (
                SELECT
                    jsonb_array_elements_text(follow_up_questions) as question,
                    theme,
                    created_at
                FROM knowledge_memory
                WHERE jsonb_array_length(follow_up_questions) > 0
            ),
            already_asked AS (
                SELECT LOWER(question) as q FROM knowledge_memory
            ),
            ranked AS (
                SELECT
                    fu.question,
                    fu.theme,
                    fu.created_at,
                    ROW_NUMBER() OVER (ORDER BY fu.created_at DESC) as rn
                FROM follow_ups fu
                WHERE LOWER(fu.question) NOT IN (SELECT q FROM already_asked)
            )
            SELECT question, theme
            FROM ranked
            WHERE rn <= :lim
            ORDER BY rn
        """), {"lim": max_questions})

        questions_to_explore = [(row[0], row[1]) for row in result.fetchall()]

    if not questions_to_explore:
        log.info("no_questions_to_explore")
        return {"explored": 0, "reason": "no_unexplored_questions"}

    log.info("exploring_questions", count=len(questions_to_explore))

    explored = 0
    total_tokens = 0
    discoveries = []

    for question, theme in questions_to_explore:
        # Check remaining token budget
        if hourly_tokens + total_tokens >= token_limit:
            log.info("token_budget_reached_mid_run", explored=explored)
            break

        log.info("exploring_question", question=question[:60], theme=theme)

        try:
            result = await agentic_search_graph.ainvoke({
                "question": question,
                "search_type": "hybrid",
                "max_sources": 8,
                "llm_calls_made": 0,
                "total_tokens_used": 0,
            })

            response = result.get("formatted_response", {})
            knowledge = response.get("knowledge", {})
            tokens = response.get("total_tokens", 0)
            total_tokens += tokens

            # Mark this as auto-explored in the knowledge record
            async with session_factory() as db:
                if knowledge.get("id"):
                    await db.execute(text("""
                        UPDATE knowledge_memory
                        SET asked_by = 'auto_explore'
                        WHERE id = :kid::uuid
                    """), {"kid": knowledge["id"]})
                    await db.commit()

            explored += 1
            question_discoveries = knowledge.get("discoveries", [])
            if question_discoveries:
                discoveries.extend(question_discoveries[:2])

            log.info(
                "question_explored",
                question=question[:50],
                confidence=response.get("confidence", 0),
                tokens=tokens,
                discoveries=len(question_discoveries),
            )

        except Exception as e:
            log.warning("question_explore_failed", question=question[:50], error=str(e))

    return {
        "explored": explored,
        "total_tokens": total_tokens,
        "discoveries": discoveries[:10],
        "questions": [q for q, _ in questions_to_explore[:explored]],
    }

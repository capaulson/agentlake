"""LangGraph agentic search pipeline.

Instead of returning a list of documents, this pipeline:
1. Searches the corpus (hybrid search)
2. Retrieves relevant chunks with full context
3. Evaluates relevance of each chunk to the question
4. Synthesizes a comprehensive answer with inline citations
5. Optionally does a follow-up search if the first pass is insufficient

Graph topology:

    search
       ↓
    retrieve_chunks
       ↓
    evaluate_relevance
       ↓
    ┌───┴───┐
    │       │
  synthesize  need_more_context?
    │       │
    │    search_followup → retrieve_more → synthesize
    │       │
    └───┬───┘
        ↓
      format_response
        ↓
       END
"""

from __future__ import annotations

import asyncio
import json
import operator
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph
from sqlalchemy import select, text

from agentlake.config import get_settings
from agentlake.core.database import _get_session_factory
from agentlake.models.document import DocumentChunk, ProcessedDocument
from agentlake.pipeline.nodes import _get_llm_client, _parse_yaml_or_json, _strip_reasoning
from agentlake.services.llm_client import LLMClient

logger = structlog.get_logger(__name__)


# ── State ──────────────────────────────────────────────────────────────────


class SourceChunk(TypedDict):
    """A chunk of evidence retrieved from the corpus."""
    document_id: str
    document_title: str
    chunk_index: int
    content: str
    source_locator: str
    relevance_score: float
    file_id: str


class Citation(TypedDict):
    """An inline citation in the answer."""
    index: int
    document_title: str
    document_id: str
    file_id: str
    chunk_index: int
    quote: str
    url: str


class AgenticSearchState(TypedDict, total=False):
    """State for the agentic search graph."""
    # Input
    question: str
    search_type: str  # "hybrid" | "keyword" | "semantic"
    max_sources: int

    # Search results
    search_results: list[dict[str, Any]]
    source_chunks: list[SourceChunk]
    relevant_chunks: list[SourceChunk]

    # Follow-up search
    needs_followup: bool
    followup_queries: list[str]
    followup_chunks: list[SourceChunk]

    # Synthesis
    answer: str
    citations: list[Citation]
    confidence: float
    topics_covered: list[str]

    # Final output
    formatted_response: dict[str, Any]

    # Metadata
    current_stage: str
    llm_calls_made: Annotated[int, operator.add]
    total_tokens_used: Annotated[int, operator.add]
    search_time_ms: float


# ── Nodes ──────────────────────────────────────────────────────────────────


async def search_node(state: AgenticSearchState) -> dict:
    """Search the corpus using hybrid search."""
    question = state["question"]
    search_type = state.get("search_type", "hybrid")
    log = logger.bind(stage="search", question=question[:50])
    log.info("agentic_search_started")

    import time
    start = time.monotonic()

    settings = get_settings()
    session_factory = _get_session_factory(settings)

    async with session_factory() as db:
        # Try multiple search strategies — natural language questions often
        # fail with websearch_to_tsquery, so fall back progressively.
        rows = []

        # Strategy 1: websearch_to_tsquery (handles quoted phrases, OR, -)
        try:
            result = await db.execute(text("""
                SELECT pd.id, pd.title, pd.summary, pd.category, pd.source_file_id,
                    ts_rank_cd(pd.search_vector, websearch_to_tsquery('english', :q)) AS rank
                FROM processed_documents pd
                WHERE pd.is_current = true
                  AND pd.search_vector @@ websearch_to_tsquery('english', :q)
                ORDER BY rank DESC LIMIT :lim
            """), {"q": question, "lim": state.get("max_sources", 10)})
            rows = result.fetchall()
        except Exception:
            pass

        # Strategy 2: plainto_tsquery (treats input as plain text, AND of all words)
        if not rows:
            try:
                result = await db.execute(text("""
                    SELECT pd.id, pd.title, pd.summary, pd.category, pd.source_file_id,
                        ts_rank_cd(pd.search_vector, plainto_tsquery('english', :q)) AS rank
                    FROM processed_documents pd
                    WHERE pd.is_current = true
                      AND pd.search_vector @@ plainto_tsquery('english', :q)
                    ORDER BY rank DESC LIMIT :lim
                """), {"q": question, "lim": state.get("max_sources", 10)})
                rows = result.fetchall()
            except Exception:
                pass

        # Strategy 3: OR search — split into individual words
        if not rows:
            words = [w.strip() for w in re.split(r'\s+', question) if len(w.strip()) > 2]
            if words:
                or_query = " | ".join(words[:10])
                try:
                    result = await db.execute(text("""
                        SELECT pd.id, pd.title, pd.summary, pd.category, pd.source_file_id,
                            ts_rank_cd(pd.search_vector, to_tsquery('english', :q)) AS rank
                        FROM processed_documents pd
                        WHERE pd.is_current = true
                          AND pd.search_vector @@ to_tsquery('english', :q)
                        ORDER BY rank DESC LIMIT :lim
                    """), {"q": or_query, "lim": state.get("max_sources", 10)})
                    rows = result.fetchall()
                except Exception:
                    pass

        # Strategy 4: ILIKE fallback (no tsvector, just substring match)
        if not rows:
            try:
                result = await db.execute(text("""
                    SELECT pd.id, pd.title, pd.summary, pd.category, pd.source_file_id,
                        1.0 AS rank
                    FROM processed_documents pd
                    WHERE pd.is_current = true
                      AND (pd.title ILIKE :pat OR pd.summary ILIKE :pat OR pd.body_markdown ILIKE :pat)
                    ORDER BY pd.created_at DESC LIMIT :lim
                """), {"pat": f"%{question[:100]}%", "lim": state.get("max_sources", 10)})
                rows = result.fetchall()
            except Exception:
                pass

        search_results = []
        for row in rows:
            search_results.append({
                "document_id": str(row[0]),
                "title": row[1],
                "summary": (row[2] or "")[:300],
                "category": row[3],
                "file_id": str(row[4]),
                "score": float(row[5]),
            })

    elapsed = (time.monotonic() - start) * 1000
    log.info("search_complete", results=len(search_results), time_ms=elapsed)

    return {
        "search_results": search_results,
        "search_time_ms": elapsed,
        "current_stage": "searching",
    }


async def retrieve_chunks_node(state: AgenticSearchState) -> dict:
    """Retrieve the actual text chunks from top search results."""
    search_results = state.get("search_results", [])
    log = logger.bind(stage="retrieve_chunks")

    if not search_results:
        return {"source_chunks": [], "current_stage": "retrieving"}

    settings = get_settings()
    session_factory = _get_session_factory(settings)
    source_chunks: list[SourceChunk] = []

    async with session_factory() as db:
        for sr in search_results[:8]:  # top 8 documents
            doc_id = sr["document_id"]
            chunks_result = await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == uuid.UUID(doc_id))
                .order_by(DocumentChunk.chunk_index)
                .limit(5)  # top 5 chunks per doc
            )
            chunks = chunks_result.scalars().all()

            for chunk in chunks:
                source_chunks.append(SourceChunk(
                    document_id=doc_id,
                    document_title=sr["title"],
                    chunk_index=chunk.chunk_index,
                    content=chunk.content[:1500],
                    source_locator=chunk.source_locator,
                    relevance_score=sr["score"],
                    file_id=sr["file_id"],
                ))

    log.info("retrieve_chunks_complete", chunks=len(source_chunks))
    return {
        "source_chunks": source_chunks,
        "current_stage": "retrieving",
    }


async def evaluate_relevance_node(state: AgenticSearchState) -> dict:
    """Use LLM to evaluate which chunks are most relevant to the question."""
    question = state["question"]
    source_chunks = state.get("source_chunks", [])
    log = logger.bind(stage="evaluate_relevance")

    if len(source_chunks) <= 3:
        # Few enough to use all of them
        return {"relevant_chunks": source_chunks, "needs_followup": False}

    log.info("evaluate_relevance_started", chunks=len(source_chunks))
    llm = _get_llm_client()

    # Build a list of chunks for the LLM to evaluate
    chunk_descriptions = []
    for i, chunk in enumerate(source_chunks[:20]):
        chunk_descriptions.append(
            f"[{i}] From \"{chunk['document_title']}\" (chunk {chunk['chunk_index']}):\n"
            f"{chunk['content'][:400]}"
        )

    try:
        result = await llm.complete(
            messages=[
                {"role": "system", "content": "You are evaluating document chunks for relevance to a question. Return a JSON array of the chunk indices (numbers) that are relevant to answering the question. Only include chunks that contain useful information. Return ONLY a JSON array of integers."},
                {"role": "user", "content": f"Question: {question}\n\nChunks:\n\n" + "\n\n---\n\n".join(chunk_descriptions)},
            ],
            purpose="classify",
            max_tokens=200,
            temperature=0.0,
        )
        tokens = result.total_tokens

        parsed = _parse_yaml_or_json(result.content)
        if isinstance(parsed, list):
            relevant_indices = [int(i) for i in parsed if isinstance(i, (int, float)) and 0 <= int(i) < len(source_chunks)]
        else:
            relevant_indices = list(range(min(5, len(source_chunks))))
    except Exception as e:
        log.warning("relevance_eval_failed", error=str(e))
        relevant_indices = list(range(min(5, len(source_chunks))))
        tokens = 0

    await llm.close()

    relevant_chunks = [source_chunks[i] for i in relevant_indices]

    # Decide if we need a follow-up search
    needs_followup = len(relevant_chunks) < 2 and len(source_chunks) > 0

    log.info("evaluate_relevance_complete", relevant=len(relevant_chunks), needs_followup=needs_followup)
    return {
        "relevant_chunks": relevant_chunks,
        "needs_followup": needs_followup,
        "llm_calls_made": 1,
        "total_tokens_used": tokens,
    }


async def generate_followup_queries_node(state: AgenticSearchState) -> dict:
    """Generate alternative search queries to find more relevant information."""
    question = state["question"]
    log = logger.bind(stage="followup_queries")
    log.info("generating_followup_queries")

    llm = _get_llm_client()
    try:
        result = await llm.complete(
            messages=[
                {"role": "system", "content": "Generate 2-3 alternative search queries to find information relevant to the user's question. Return a JSON array of query strings. Return ONLY the JSON array."},
                {"role": "user", "content": f"Original question: {question}\n\nThe initial search didn't find enough relevant results. Generate alternative queries."},
            ],
            purpose="classify",
            max_tokens=200,
            temperature=0.5,
        )
        tokens = result.total_tokens
        parsed = _parse_yaml_or_json(result.content)
        queries = [str(q) for q in parsed] if isinstance(parsed, list) else [question]
    except Exception:
        queries = [question]
        tokens = 0

    await llm.close()
    return {
        "followup_queries": queries,
        "llm_calls_made": 1,
        "total_tokens_used": tokens,
    }


async def followup_search_node(state: AgenticSearchState) -> dict:
    """Run follow-up searches with alternative queries."""
    queries = state.get("followup_queries", [])
    log = logger.bind(stage="followup_search")

    settings = get_settings()
    session_factory = _get_session_factory(settings)
    followup_chunks: list[SourceChunk] = []
    existing_doc_ids = {c["document_id"] for c in state.get("relevant_chunks", [])}

    async with session_factory() as db:
        for q in queries[:3]:
            result = await db.execute(text("""
                SELECT pd.id, pd.title, pd.summary, pd.category, pd.source_file_id,
                    ts_rank_cd(pd.search_vector, websearch_to_tsquery('english', :q)) AS rank
                FROM processed_documents pd
                WHERE pd.is_current = true
                  AND pd.search_vector @@ websearch_to_tsquery('english', :q)
                ORDER BY rank DESC LIMIT 5
            """), {"q": q})

            for row in result.fetchall():
                doc_id = str(row[0])
                if doc_id in existing_doc_ids:
                    continue
                existing_doc_ids.add(doc_id)

                chunks_result = await db.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == uuid.UUID(doc_id))
                    .order_by(DocumentChunk.chunk_index)
                    .limit(3)
                )
                for chunk in chunks_result.scalars().all():
                    followup_chunks.append(SourceChunk(
                        document_id=doc_id,
                        document_title=row[1],
                        chunk_index=chunk.chunk_index,
                        content=chunk.content[:1500],
                        source_locator=chunk.source_locator,
                        relevance_score=float(row[5]),
                        file_id=str(row[4]),
                    ))

    # Merge with existing relevant chunks
    all_relevant = list(state.get("relevant_chunks", [])) + followup_chunks
    log.info("followup_search_complete", new_chunks=len(followup_chunks))

    return {
        "relevant_chunks": all_relevant,
        "followup_chunks": followup_chunks,
    }


async def synthesize_answer_node(state: AgenticSearchState) -> dict:
    """Synthesize a comprehensive answer from relevant chunks with citations."""
    question = state["question"]
    relevant_chunks = state.get("relevant_chunks", [])
    log = logger.bind(stage="synthesize")
    log.info("synthesize_started", chunks=len(relevant_chunks))

    if not relevant_chunks:
        return {
            "answer": "I couldn't find any relevant information in the data lake to answer this question.",
            "citations": [],
            "confidence": 0.0,
            "topics_covered": [],
            "llm_calls_made": 0,
            "total_tokens_used": 0,
        }

    # Build context with numbered sources
    context_parts = []
    source_map: dict[int, SourceChunk] = {}
    for i, chunk in enumerate(relevant_chunks[:15]):  # limit to 15 chunks
        source_num = i + 1
        source_map[source_num] = chunk
        context_parts.append(
            f"[Source {source_num}] \"{chunk['document_title']}\" "
            f"(chunk {chunk['chunk_index']}, {chunk['source_locator']}):\n"
            f"{chunk['content'][:1000]}"
        )

    context = "\n\n---\n\n".join(context_parts)

    llm = _get_llm_client()
    try:
        result = await llm.complete(
            messages=[
                {"role": "system", "content": """You are a research analyst answering questions using a corporate data lake.

Rules:
1. Answer the question comprehensively using ONLY the provided sources
2. Cite sources inline using [Source N] notation for every claim
3. If sources contain conflicting information, note the discrepancy
4. If the sources don't fully answer the question, say what's missing
5. Structure your answer with clear paragraphs
6. At the end, rate your confidence (0-100%) based on source quality
7. List the main topics covered

Format your response as:

ANSWER:
(your comprehensive answer with [Source N] citations)

CONFIDENCE: (0-100)
TOPICS: (comma-separated list of topics covered)"""},
                {"role": "user", "content": f"Question: {question}\n\nSources:\n\n{context}"},
            ],
            purpose="summarize",
            max_tokens=3000,
            temperature=0.3,
        )
        tokens = result.total_tokens
        response_text = result.content

    except Exception as e:
        log.warning("synthesis_failed", error=str(e))
        response_text = "I encountered an error while synthesizing the answer. Here are the relevant sources I found."
        tokens = 0

    await llm.close()

    # Parse the response
    answer = response_text
    confidence = 0.5
    topics: list[str] = []

    # Extract structured parts
    if "ANSWER:" in response_text:
        parts = response_text.split("CONFIDENCE:")
        answer = parts[0].replace("ANSWER:", "").strip()
        if len(parts) > 1:
            rest = parts[1]
            try:
                conf_match = re.search(r'(\d+)', rest)
                if conf_match:
                    confidence = min(int(conf_match.group(1)), 100) / 100.0
            except (ValueError, AttributeError):
                pass
            if "TOPICS:" in rest:
                topics_text = rest.split("TOPICS:")[1].strip()
                topics = [t.strip() for t in topics_text.split(",") if t.strip()]

    # Extract citations from [Source N] references in the answer
    citations: list[Citation] = []
    seen_sources = set()
    for match in re.finditer(r'\[Source (\d+)\]', answer):
        source_num = int(match.group(1))
        if source_num in source_map and source_num not in seen_sources:
            seen_sources.add(source_num)
            chunk = source_map[source_num]
            citations.append(Citation(
                index=source_num,
                document_title=chunk["document_title"],
                document_id=chunk["document_id"],
                file_id=chunk["file_id"],
                chunk_index=chunk["chunk_index"],
                quote=chunk["content"][:200],
                url=f"/api/v1/vault/files/{chunk['file_id']}/download#chunk={chunk['chunk_index']}",
            ))

    log.info("synthesize_complete", citations=len(citations), confidence=confidence)
    return {
        "answer": answer,
        "citations": citations,
        "confidence": confidence,
        "topics_covered": topics,
        "llm_calls_made": 1,
        "total_tokens_used": tokens,
    }


async def format_response_node(state: AgenticSearchState) -> dict:
    """Format the final response."""
    return {
        "formatted_response": {
            "question": state["question"],
            "answer": state.get("answer", ""),
            "citations": state.get("citations", []),
            "confidence": state.get("confidence", 0),
            "topics_covered": state.get("topics_covered", []),
            "sources_consulted": len(state.get("search_results", [])),
            "chunks_analyzed": len(state.get("source_chunks", [])),
            "chunks_used": len(state.get("relevant_chunks", [])),
            "search_time_ms": state.get("search_time_ms", 0),
            "llm_calls": state.get("llm_calls_made", 0),
            "total_tokens": state.get("total_tokens_used", 0),
            "had_followup": state.get("needs_followup", False),
        },
        "current_stage": "complete",
    }


# ═══════════════════════════════════════════════════════════════════════════
# INSTITUTIONAL MEMORY NODES
# ═══════════════════════════════════════════════════════════════════════════


async def record_knowledge_node(state: AgenticSearchState) -> dict:
    """Record this question as institutional memory.

    Classifies the question, finds related past questions,
    generates follow-up questions the system should explore,
    and checks if it's time for an automatic deep analysis.
    """
    question = state["question"]
    answer = state.get("answer", "")
    confidence = state.get("confidence", 0)
    citations = state.get("citations", [])
    topics = state.get("topics_covered", [])
    log = logger.bind(stage="record_knowledge")
    log.info("recording_knowledge", question=question[:50])

    settings = get_settings()
    session_factory = _get_session_factory(settings)
    llm = _get_llm_client()

    # Classify the question and generate follow-ups in one LLM call
    try:
        classify_result = await llm.complete(
            messages=[
                {"role": "system", "content": """Analyze this question that was asked of a corporate data lake. Return JSON:
{
  "theme": "2-3 word theme (e.g., 'security posture', 'revenue growth', 'team structure')",
  "intent": "one of: factual, analytical, exploratory, comparative, strategic",
  "entities_mentioned": ["entity names mentioned in the question"],
  "discoveries": ["1-3 key things learned from the answer"],
  "follow_up_questions": ["3-5 deeper questions the system should proactively investigate based on this question and answer"],
  "curiosity_note": "One sentence about what pattern this question reveals about organizational interests"
}
Return ONLY valid JSON."""},
                {"role": "user", "content": f"Question: {question}\n\nAnswer (confidence {confidence:.0%}):\n{answer[:2000]}"},
            ],
            purpose="classify",
            max_tokens=1000,
            temperature=0.3,
        )
        meta = _parse_yaml_or_json(_strip_reasoning(classify_result.content))
        if not isinstance(meta, dict):
            meta = {}
        tokens_used = classify_result.total_tokens
    except Exception as e:
        log.warning("knowledge_classify_failed", error=str(e))
        meta = {}
        tokens_used = 0

    # Generate embedding for the question (for similarity search)
    try:
        emb = await llm.embed([question])
        q_embedding = emb[0] if emb else None
    except Exception:
        q_embedding = None

    await llm.close()

    # Find related past questions
    related_ids = []
    async with session_factory() as db:
        from agentlake.models.knowledge import KnowledgeMemory

        if q_embedding:
            # Semantic similarity search on past questions
            related_result = await db.execute(text("""
                SELECT id, question, 1 - (question_embedding <=> cast(:emb as vector)) as similarity
                FROM knowledge_memory
                WHERE question_embedding IS NOT NULL
                ORDER BY question_embedding <=> cast(:emb as vector)
                LIMIT 5
            """), {"emb": str(q_embedding)})
            for row in related_result.fetchall():
                if row[2] > 0.7:  # similarity threshold
                    related_ids.append({"id": str(row[0]), "question": row[1], "similarity": round(row[2], 3)})

        # Store the knowledge memory record
        km = KnowledgeMemory(
            question=question,
            answer=answer[:5000] if answer else None,
            confidence=confidence,
            sources_used=len(citations),
            tokens_used=state.get("total_tokens_used", 0) + tokens_used,
            question_embedding=q_embedding,
            theme=meta.get("theme"),
            intent=meta.get("intent"),
            entities_mentioned=meta.get("entities_mentioned", []),
            discoveries=meta.get("discoveries", []),
            follow_up_questions=meta.get("follow_up_questions", []),
            related_question_ids=related_ids,
            asked_by="user",
        )
        db.add(km)
        await db.flush()
        knowledge_id = str(km.id)

        # Autonomous exploration — trigger after every question
        # The token budget in auto_explore controls cost, not a question threshold
        from sqlalchemy import func as sa_func
        total_questions = await db.scalar(
            select(sa_func.count()).select_from(KnowledgeMemory)
        )

        # Read settings
        settings_result = await db.execute(text("SELECT key, value FROM system_settings"))
        db_settings = {r[0]: r[1] for r in settings_result.fetchall()}
        auto_enabled = db_settings.get("auto_explore_enabled", "true").lower() == "true"

        # Check hourly token budget
        hourly_result = await db.execute(text("""
            SELECT COALESCE(SUM(tokens_used), 0) FROM knowledge_memory
            WHERE created_at > now() - interval '1 hour'
        """))
        hourly_tokens = hourly_result.scalar() or 0
        token_limit = int(db_settings.get("auto_explore_max_tokens_per_hour", "50000"))

        should_explore = auto_enabled and hourly_tokens < token_limit
        if should_explore:
            log.info("triggering_autonomous_exploration", hourly_tokens=hourly_tokens, limit=token_limit)
            try:
                from agentlake.workers.celery_app import celery_app
                max_q = int(db_settings.get("auto_explore_max_questions_per_run", "5"))
                celery_app.send_task("auto_explore", kwargs={
                    "max_questions": max_q,
                }, queue="low")
            except Exception as e:
                log.warning("auto_explore_trigger_failed", error=str(e))

        await db.commit()

    log.info(
        "knowledge_recorded",
        id=knowledge_id,
        theme=meta.get("theme"),
        intent=meta.get("intent"),
        discoveries=len(meta.get("discoveries", [])),
        follow_ups=len(meta.get("follow_up_questions", [])),
        related=len(related_ids),
        total_questions=total_questions,
        auto_explore=should_explore,
    )

    return {
        "formatted_response": {
            **state.get("formatted_response", {}),
            "knowledge": {
                "id": knowledge_id,
                "theme": meta.get("theme"),
                "intent": meta.get("intent"),
                "discoveries": meta.get("discoveries", []),
                "follow_up_questions": meta.get("follow_up_questions", []),
                "related_questions": related_ids,
                "curiosity_note": meta.get("curiosity_note", ""),
                "total_questions_asked": total_questions,
                "auto_explore_triggered": should_explore,
            },
        },
        "current_stage": "complete",
    }


# ── Graph Definition ───────────────────────────────────────────────────────


def _check_followup(state: AgenticSearchState) -> str:
    """Decide whether to do a follow-up search."""
    if state.get("needs_followup", False):
        return "generate_followup"
    return "synthesize"


def create_agentic_search_graph() -> StateGraph:
    """Build the agentic search graph.

    Topology:
        search → retrieve_chunks → evaluate_relevance
            → [synthesize | generate_followup → followup_search → synthesize]
            → format_response → END
    """
    builder = StateGraph(AgenticSearchState)

    builder.add_node("search", search_node)
    builder.add_node("retrieve_chunks", retrieve_chunks_node)
    builder.add_node("evaluate_relevance", evaluate_relevance_node)
    builder.add_node("generate_followup", generate_followup_queries_node)
    builder.add_node("followup_search", followup_search_node)
    builder.add_node("synthesize", synthesize_answer_node)
    builder.add_node("format_response", format_response_node)
    builder.add_node("record_knowledge", record_knowledge_node)

    builder.set_entry_point("search")
    builder.add_edge("search", "retrieve_chunks")
    builder.add_edge("retrieve_chunks", "evaluate_relevance")

    builder.add_conditional_edges(
        "evaluate_relevance",
        _check_followup,
        {
            "synthesize": "synthesize",
            "generate_followup": "generate_followup",
        },
    )

    builder.add_edge("generate_followup", "followup_search")
    builder.add_edge("followup_search", "synthesize")
    builder.add_edge("synthesize", "format_response")
    builder.add_edge("format_response", "record_knowledge")
    builder.add_edge("record_knowledge", END)

    return builder.compile()


agentic_search_graph = create_agentic_search_graph()

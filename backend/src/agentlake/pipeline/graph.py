"""LangGraph processing pipeline for AgentLake.

With GPT-5.4 (1M context), the pipeline does single-pass full-document
analysis. The entire raw document is sent in one LLM call.

Graph topology:

    extract
       ↓
     chunk  (for embeddings + citations, not for LLM)
       ↓
  full_document_analysis  (1 LLM call → title, summary, category,
       ↓                   entities, people, relationships, tags,
     cite                  dates, metrics, cross-refs, quotes)
       ↓
     embed
       ↓
     store
       ↓
      END

7 nodes replaced by 1. 7+ LLM calls replaced by 1.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from agentlake.pipeline.nodes import (
    chunk_node,
    cite_node,
    embed_node,
    extract_node,
    full_document_analysis_node,
    handle_error_node,
    store_node,
)
from agentlake.pipeline.state import PipelineState


def create_processing_graph() -> StateGraph:
    """Build and compile the document processing graph."""
    builder = StateGraph(PipelineState)

    # ── Add nodes ──────────────────────────────────────────────────────
    builder.add_node("extract", extract_node)
    builder.add_node("chunk", chunk_node)
    builder.add_node("full_document_analysis", full_document_analysis_node)
    builder.add_node("cite", cite_node)
    builder.add_node("embed", embed_node)
    builder.add_node("store", store_node)
    builder.add_node("handle_error", handle_error_node)

    # ── Linear flow ───────────────────────────────────────────────────
    builder.set_entry_point("extract")
    builder.add_edge("extract", "chunk")
    builder.add_edge("chunk", "full_document_analysis")
    builder.add_edge("full_document_analysis", "cite")
    builder.add_edge("cite", "embed")
    builder.add_edge("embed", "store")
    builder.add_edge("store", END)
    builder.add_edge("handle_error", END)

    return builder.compile()


# Module-level compiled graph
processing_graph = create_processing_graph()

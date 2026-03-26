"""Cross-document intelligence analysis — GPT-5.4 single-pass.

Sends ALL document metadata (entities, people, relationships, tags,
dates, metrics) in one LLM call and gets back a comprehensive
intelligence report.

    gather_documents → single_pass_analysis → [update_graph | store_insights] → END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from agentlake.pipeline.cross_document_nodes import (
    gather_documents_node,
    single_pass_analysis_node,
    store_insights_node,
    update_graph_node,
)
from agentlake.pipeline.cross_document_state import CrossDocState


def create_cross_doc_graph() -> StateGraph:
    builder = StateGraph(CrossDocState)

    builder.add_node("gather_documents", gather_documents_node)
    builder.add_node("single_pass_analysis", single_pass_analysis_node)
    builder.add_node("update_graph", update_graph_node)
    builder.add_node("store_insights", store_insights_node)

    builder.set_entry_point("gather_documents")
    builder.add_edge("gather_documents", "single_pass_analysis")
    builder.add_edge("single_pass_analysis", "update_graph")
    builder.add_edge("single_pass_analysis", "store_insights")
    builder.add_edge("update_graph", END)
    builder.add_edge("store_insights", END)

    return builder.compile()


cross_doc_graph = create_cross_doc_graph()

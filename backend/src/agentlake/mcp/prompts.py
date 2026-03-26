"""MCP prompt definitions for AgentLake.

Pre-built prompt templates that guide an LLM through multi-step workflows
using the AgentLake MCP tools:
  - research_topic   -- deep research across the data lake
  - entity_briefing  -- comprehensive briefing on a person, org, or product
"""

from __future__ import annotations

from mcp.server import Server
from mcp.types import Prompt, PromptArgument, PromptMessage, TextContent

from agentlake.mcp.client import AgentLakeClient


def register_prompts(server: Server, client: AgentLakeClient) -> None:
    """Register AgentLake prompt templates on the MCP server."""

    @server.list_prompts()
    async def list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name="research_topic",
                description=(
                    "Research a topic across the AgentLake data lake. "
                    "Discovers available data, searches with multiple query "
                    "variations, fetches full documents, verifies citations, "
                    "and synthesizes findings."
                ),
                arguments=[
                    PromptArgument(
                        name="topic",
                        description="The topic to research",
                        required=True,
                    ),
                    PromptArgument(
                        name="depth",
                        description=(
                            "Research depth: 'quick' (top 3 results), "
                            "'standard' (top 5, verify key citations), or "
                            "'thorough' (all relevant results, full verification)"
                        ),
                        required=False,
                    ),
                ],
            ),
            Prompt(
                name="entity_briefing",
                description=(
                    "Generate a comprehensive briefing about a person, "
                    "organization, product, or technology based on all "
                    "available data in AgentLake."
                ),
                arguments=[
                    PromptArgument(
                        name="entity_name",
                        description="Name of the entity to brief on",
                        required=True,
                    ),
                    PromptArgument(
                        name="entity_type",
                        description=(
                            "Type of entity: person, organization, product, "
                            "technology, or leave blank for auto-detect"
                        ),
                        required=False,
                    ),
                ],
            ),
        ]

    @server.get_prompt()
    async def get_prompt(
        name: str, arguments: dict[str, str] | None = None
    ) -> list[PromptMessage]:
        arguments = arguments or {}

        if name == "research_topic":
            return _build_research_topic_prompt(arguments)
        elif name == "entity_briefing":
            return _build_entity_briefing_prompt(arguments)
        else:
            return [
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Unknown prompt: {name}",
                    ),
                )
            ]


def _build_research_topic_prompt(
    arguments: dict[str, str],
) -> list[PromptMessage]:
    """Build the multi-step research prompt."""
    topic = arguments.get("topic", "")
    depth = arguments.get("depth", "standard")

    depth_instructions = {
        "quick": (
            "- Search once with the main query\n"
            "- Read the top 3 results\n"
            "- Provide a concise summary"
        ),
        "standard": (
            "- Search with 2-3 query variations (synonyms, related terms)\n"
            "- Read the top 5 most relevant results in full\n"
            "- Verify key citations by fetching citation details\n"
            "- Provide a detailed summary with source references"
        ),
        "thorough": (
            "- Search with 5+ query variations covering different angles\n"
            "- Read ALL relevant results in full\n"
            "- Verify ALL citations against source data\n"
            "- Explore the entity graph for related entities\n"
            "- Identify gaps or contradictions in the data\n"
            "- Provide an exhaustive analysis with full source attribution"
        ),
    }

    instructions = depth_instructions.get(depth, depth_instructions["standard"])

    text = f"""Research the topic "{topic}" using the AgentLake data lake.

Follow these steps:

1. **Discover** -- Use agentlake_discover to understand what data is available in the lake (total documents, categories, tags, entity types).

2. **Search** -- Use agentlake_search with different query variations to find relevant documents. Try the main topic, synonyms, and related concepts. Use hybrid search for best results.

3. **Read** -- For the most relevant search results, use agentlake_get_document to retrieve the full processed content including markdown body and metadata.

4. **Verify** -- Use agentlake_get_citations on key documents to verify that claims are supported by the original source data. Note any claims that lack strong citations.

5. **Explore connections** -- If the documents mention entities (people, organizations, products, technologies), use agentlake_graph_explore to understand how they relate to each other and to the topic.

6. **Synthesize** -- Compile your findings into a comprehensive summary. Include:
   - Key findings and insights
   - Supporting evidence with document references
   - Entity relationships relevant to the topic
   - Confidence level for each finding based on citation strength
   - Gaps or areas where more data would be helpful

Depth: {depth}
{instructions}

Important:
- Always cite which AgentLake documents your findings come from
- Note when information comes from a single source vs. multiple corroborating sources
- Flag any contradictions between documents
- Use the citation links format: [N](document_id) so findings are traceable
"""

    return [
        PromptMessage(
            role="user",
            content=TextContent(type="text", text=text),
        )
    ]


def _build_entity_briefing_prompt(
    arguments: dict[str, str],
) -> list[PromptMessage]:
    """Build the entity briefing prompt."""
    entity_name = arguments.get("entity_name", "")
    entity_type = arguments.get("entity_type", "")

    type_hint = f" ({entity_type})" if entity_type else ""

    text = f"""Generate a comprehensive briefing about "{entity_name}"{type_hint} using the AgentLake data lake.

Follow these steps:

1. **Find the entity** -- Use agentlake_graph_explore with query="{entity_name}"{f' and entity_type="{entity_type}"' if entity_type else ''} to locate the entity in the knowledge graph.

2. **Map relationships** -- If found, use agentlake_graph_explore with the entity_id and depth=2 to map out its connections to other entities (people, organizations, products, technologies).

3. **Search for mentions** -- Use agentlake_search to find all documents that mention "{entity_name}". Try variations of the name if applicable.

4. **Read relevant documents** -- For each relevant search result, use agentlake_get_document to retrieve the full content.

5. **Compile the briefing** -- Organize your findings into these sections:

   ## Overview
   Key facts and description of the entity.

   ## Relationships & Connections
   Other entities this one is connected to, with the nature of each relationship.

   ## Timeline of Mentions
   Chronological summary of when and where this entity appears in the data lake.

   ## Key Documents
   List of the most important documents about this entity, with brief descriptions.

   ## Detailed Findings
   In-depth analysis drawn from the document contents, with citations.

   ## Open Questions
   Gaps in available data, unresolved questions, or areas that need more information.

Important:
- Cite every factual claim with the source document ID
- Distinguish between directly stated facts and inferences
- Note the recency and reliability of each data source
- If the entity is not found in the graph, rely on document search results
"""

    return [
        PromptMessage(
            role="user",
            content=TextContent(type="text", text=text),
        )
    ]

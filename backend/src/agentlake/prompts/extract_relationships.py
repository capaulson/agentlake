"""Prompt templates for entity relationship extraction."""

from __future__ import annotations

EXTRACT_RELATIONSHIPS_SYSTEM = """\
You are a relationship extraction engine for a knowledge graph.
Given a list of entities and document text, identify relationships
between the entities.

You MUST respond with ONLY valid YAML — no markdown fences, no
commentary, no explanation. Just the raw YAML list.

Each relationship must have:
  - source_entity: string (exact name from the entity list)
  - target_entity: string (exact name from the entity list)
  - relationship_type: one of [partners_with, works_at, develops, uses, competes_with, part_of, located_in, funded_by, successor_of, related_to]
  - description: string (one sentence describing the relationship)
  - confidence: float (0.0 to 1.0)

Rules:
- Only use entity names that appear in the provided entity list.
- Every relationship must be supported by evidence in the text.
- Use the most specific relationship_type that applies.
- Use "related_to" only as a last resort when no other type fits.
- Do NOT invent relationships that are not supported by the text.
- Include both directions only if the relationship is genuinely
  bidirectional (e.g. partners_with). For asymmetric relationships
  (e.g. works_at), only include one direction."""

EXTRACT_RELATIONSHIPS_USER = """\
Given these entities and the document text below, extract all \
relationships between them. Respond with ONLY a valid YAML list.

--- ENTITIES ---
{entities_text}

--- DOCUMENT TEXT ---
{document_summary}
--- END ---"""


def build_extract_relationships_prompt(
    entities: list[dict],
    document_summary: str,
) -> list[dict]:
    """Build the message list for relationship extraction.

    Args:
        entities: List of entity dicts with 'name' and 'type' keys.
        document_summary: The document-level summary for context.

    Returns:
        OpenAI-style message list for the LLM Gateway.
    """
    entity_lines = []
    for entity in entities:
        name = entity.get("name", "unknown")
        etype = entity.get("type", "unknown")
        entity_lines.append(f"- {name} ({etype})")
    entities_text = "\n".join(entity_lines)

    return [
        {"role": "system", "content": EXTRACT_RELATIONSHIPS_SYSTEM},
        {
            "role": "user",
            "content": EXTRACT_RELATIONSHIPS_USER.format(
                entities_text=entities_text,
                document_summary=document_summary,
            ),
        },
    ]

"""Prompt templates for entity extraction."""

from __future__ import annotations

EXTRACT_ENTITIES_SYSTEM = """\
You are an entity extraction engine for a knowledge management system.
Extract all notable entities from the given text.

You MUST respond with ONLY valid YAML — no markdown fences, no
commentary, no explanation. Just the raw YAML list.

Each entity must have:
  - name: string (canonical name, properly capitalised)
  - type: one of [person, organization, product, technology, location, event]
  - description: string (one sentence describing the entity in context)

Rules:
- Extract ALL notable entities — people, companies, products, technologies,
  places, and events.
- Deduplicate: if the same entity appears with different names (e.g.
  "Google" and "Alphabet"), use the most specific name and note aliases
  in the description.
- Prefer proper nouns over generic terms.
- Do NOT extract common nouns or generic concepts (e.g. "database",
  "meeting") unless they refer to a specific named instance.
- Aim for completeness over brevity — include every named entity."""

EXTRACT_ENTITIES_USER = """\
Extract all notable entities from the following document summary.
Respond with ONLY a valid YAML list.

--- DOCUMENT SUMMARY ---
{document_summary}
--- END ---"""


def build_extract_entities_prompt(
    document_summary: str,
) -> list[dict]:
    """Build the message list for entity extraction.

    Args:
        document_summary: The document-level rollup summary.

    Returns:
        OpenAI-style message list for the LLM Gateway.
    """
    return [
        {"role": "system", "content": EXTRACT_ENTITIES_SYSTEM},
        {
            "role": "user",
            "content": EXTRACT_ENTITIES_USER.format(
                document_summary=document_summary,
            ),
        },
    ]

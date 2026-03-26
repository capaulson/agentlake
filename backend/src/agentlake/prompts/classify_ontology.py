"""Prompt templates for ontology classification (Common Data Ontology)."""

from __future__ import annotations

CLASSIFY_ONTOLOGY_SYSTEM = """\
You are a document classifier for a knowledge management system.
You must classify documents according to a fixed ontology and extract
date metadata.

You MUST respond with ONLY valid YAML — no markdown fences, no
commentary, no explanation. Just the raw YAML block.

Schema:
  title: string (concise document title, max 100 characters)
  category: one of [technical, business, operational, research, communication, reference]
  subcategory: string (free-form, more specific classification)
  document_date: string or null (ISO 8601 date, e.g. "2024-01-15")
  date_range_start: string or null (ISO 8601 date)
  date_range_end: string or null (ISO 8601 date)
  confidence_score: float (0.0 to 1.0, your confidence in the classification)
  tags: list of strings (3-8 descriptive tags)
  language: string (ISO 639-1 code, e.g. "en")

Category definitions:
- technical: Engineering docs, API specs, architecture, code, technical reports
- business: Financial reports, strategy docs, market analysis, proposals
- operational: SOPs, runbooks, meeting notes, project plans, status updates
- research: Academic papers, literature reviews, experimental results
- communication: Emails, memos, announcements, correspondence
- reference: Manuals, guides, glossaries, policies, legal documents"""

CLASSIFY_ONTOLOGY_USER = """\
Classify the following document based on its summary and chunk summaries.
Respond with ONLY valid YAML.

--- DOCUMENT SUMMARY ---
{document_summary}

--- CHUNK SUMMARIES ---
{chunk_summaries_text}
--- END ---"""


def build_classify_prompt(
    document_summary: str,
    chunk_summaries: list[str],
) -> list[dict]:
    """Build the message list for ontology classification.

    Args:
        document_summary: The document-level rollup summary.
        chunk_summaries: Individual chunk summaries for additional context.

    Returns:
        OpenAI-style message list for the LLM Gateway.
    """
    # Include first few chunk summaries for context (limit to avoid
    # excessive tokens)
    limited = chunk_summaries[:10]
    chunk_text = "\n\n".join(
        f"Chunk {i}: {s}" for i, s in enumerate(limited, 1)
    )

    return [
        {"role": "system", "content": CLASSIFY_ONTOLOGY_SYSTEM},
        {
            "role": "user",
            "content": CLASSIFY_ONTOLOGY_USER.format(
                document_summary=document_summary,
                chunk_summaries_text=chunk_text,
            ),
        },
    ]

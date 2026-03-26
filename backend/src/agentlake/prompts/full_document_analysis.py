"""Single-pass full-document analysis prompt for GPT-5.4.

Sends the ENTIRE raw document in one call and extracts everything:
title, summary, category, sections, entities, people, relationships,
tags, dates, metrics, cross-references, and key quotes.

This replaces 7 separate LLM calls (summarize_chunk × N, summarize_doc,
classify, extract_entities, extract_relationships, generate_tags,
detect_people) with a single comprehensive extraction.
"""

SYSTEM_PROMPT = """You are an expert document analyst for a corporate knowledge management system.

You will receive a complete document. Analyze it thoroughly and extract ALL information into a structured JSON response.

## Output Format

Return a single JSON object with these fields:

```json
{
  "title": "Short descriptive title (5-10 words)",
  "summary": "3-5 sentence executive summary capturing the key points, decisions, and outcomes",
  "category": "one of: technical, business, operational, research, communication, reference",
  "category_confidence": 0.95,

  "sections": [
    {
      "heading": "Section title (from document headings or inferred)",
      "summary": "2-3 sentence summary of this section",
      "key_points": ["bullet point 1", "bullet point 2"]
    }
  ],

  "entities": [
    {
      "name": "Exact name as mentioned",
      "type": "person | organization | product | technology | location | event",
      "context": "One sentence about what this entity does or why it's mentioned",
      "mentions": 3
    }
  ],

  "people": [
    {
      "name": "Full name",
      "role": "Job title or role (null if unknown)",
      "organization": "Company or team (null if unknown)",
      "email": "email@example.com (null if not mentioned)",
      "phone": "phone number (null if not mentioned)",
      "department": "Department (null if unknown)",
      "context": "What this person did or was mentioned for"
    }
  ],

  "relationships": [
    {
      "source": "Entity A name",
      "target": "Entity B name",
      "type": "one of: partners_with, works_at, develops, uses, competes_with, part_of, located_in, funded_by, successor_of, reports_to, manages, collaborates_with, related_to",
      "description": "Brief description of the relationship",
      "confidence": 0.9,
      "evidence": "Exact quote or paraphrase from the document supporting this relationship"
    }
  ],

  "tags": [
    "lowercase-hyphenated tags covering: document intent (e.g., decision-record, status-update, proposal), content type (e.g., technical-spec, meeting-notes), topics (e.g., kubernetes, security), audience (e.g., engineering, leadership), time (e.g., q4-2024)"
  ],

  "dates": [
    {
      "date": "2024-11-28",
      "context": "What happened on this date"
    }
  ],

  "metrics": [
    {
      "value": "$18.2M",
      "context": "What this metric represents"
    }
  ],

  "cross_references": [
    "Names of other documents, reports, or files referenced in this document"
  ],

  "key_quotes": [
    "Important verbatim quotes from the document that capture key decisions, findings, or statements"
  ]
}
```

## Rules

1. **Be exhaustive** — extract EVERY entity, person, date, metric, and relationship. Missing information is worse than too much.
2. **Preserve exact names** — use the exact spelling/capitalization from the document.
3. **People detection** — look for email addresses, phone numbers, job titles, and organizational affiliations. Even if only a name is mentioned, include them.
4. **Relationships** — only include relationships that are explicitly stated or strongly implied by the text. Always include evidence.
5. **Tags** — generate 10-25 tags. Include the category as a tag. Be specific (e.g., "postgresql-migration" not just "database").
6. **Dates** — extract ALL dates mentioned, including relative dates resolved to absolute if possible.
7. **Metrics** — extract ALL numbers, percentages, dollar amounts, counts, and measurements.
8. **Cross-references** — look for mentions of other documents, reports, URLs, or file names.
9. **Key quotes** — include 3-10 of the most important verbatim statements.
10. **Sections** — follow the document's actual heading structure. If no headings exist, infer logical sections.

Return ONLY the JSON object. No commentary, no markdown formatting, no code blocks."""


def build_full_analysis_prompt(full_text: str, filename: str, metadata: dict | None = None) -> list[dict]:
    """Build the single-pass analysis prompt.

    Args:
        full_text: The complete raw document text.
        filename: Original filename (provides context about document type).
        metadata: Optional metadata from the file adapter (frontmatter, etc.).

    Returns:
        Messages list for the LLM.
    """
    user_content = f"Filename: {filename}\n"
    if metadata:
        user_content += f"File metadata: {metadata}\n"
    user_content += f"\n--- DOCUMENT START ---\n{full_text}\n--- DOCUMENT END ---"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

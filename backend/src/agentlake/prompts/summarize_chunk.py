"""Prompt templates for chunk-level summarization."""

from __future__ import annotations

SUMMARIZE_CHUNK_SYSTEM = """\
You are a precise document summarizer for a knowledge management system.
Your summaries will be stored alongside the original content and used for
search, retrieval, and knowledge discovery.

Rules:
- Preserve ALL key facts, figures, names, dates, and technical details.
- Use markdown formatting (headings, lists, bold for emphasis).
- Keep the summary concise but comprehensive — aim for 20-30% of the
  original length.
- Do NOT add information that is not present in the source text.
- Do NOT include preamble like "This chunk discusses..." — go straight
  to the content.
- Maintain the same tone and domain terminology as the original."""

SUMMARIZE_CHUNK_USER = """\
Summarize the following chunk from "{filename}" (source: {source_locator}).
Preserve key facts, figures, names, and dates. Keep the summary concise \
but comprehensive. Use markdown formatting.

--- CHUNK ---
{content}
--- END CHUNK ---"""


def build_summarize_chunk_prompt(
    content: str,
    filename: str,
    source_locator: str,
) -> list[dict]:
    """Build the message list for chunk summarization.

    Args:
        content: The chunk text to summarize.
        filename: Name of the source file.
        source_locator: Human-readable locator (e.g. "page:3").

    Returns:
        OpenAI-style message list for the LLM Gateway.
    """
    return [
        {"role": "system", "content": SUMMARIZE_CHUNK_SYSTEM},
        {
            "role": "user",
            "content": SUMMARIZE_CHUNK_USER.format(
                content=content,
                filename=filename,
                source_locator=source_locator,
            ),
        },
    ]

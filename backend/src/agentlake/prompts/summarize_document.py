"""Prompt templates for document-level rollup summarization."""

from __future__ import annotations

SUMMARIZE_DOCUMENT_SYSTEM = """\
You are a precise document summarizer for a knowledge management system.
You are given individual chunk summaries from a single document and must
produce a cohesive, high-level summary of the entire document.

Rules:
- Synthesize the chunk summaries into a unified narrative — do NOT just
  concatenate them.
- Preserve the most important facts, figures, names, dates, and
  conclusions.
- Use markdown formatting (headings, lists, bold for emphasis).
- Aim for 3-8 paragraphs depending on document complexity.
- Include a one-sentence TL;DR at the very top in bold.
- Do NOT add information that is not present in the chunk summaries.
- Do NOT include preamble like "This document contains..." — go straight
  to the content."""

SUMMARIZE_DOCUMENT_USER = """\
Below are {chunk_count} chunk summaries from the file "{filename}".
Produce a cohesive document-level summary that synthesizes all the \
information. Start with a one-sentence bold TL;DR.

{chunk_summaries_text}"""


def build_summarize_document_prompt(
    chunk_summaries: list[str],
    filename: str,
) -> list[dict]:
    """Build the message list for document-level rollup summarization.

    Args:
        chunk_summaries: List of individual chunk summary texts.
        filename: Name of the source file.

    Returns:
        OpenAI-style message list for the LLM Gateway.
    """
    numbered = []
    for i, summary in enumerate(chunk_summaries, 1):
        numbered.append(f"### Chunk {i}\n{summary}")
    chunk_summaries_text = "\n\n".join(numbered)

    return [
        {"role": "system", "content": SUMMARIZE_DOCUMENT_SYSTEM},
        {
            "role": "user",
            "content": SUMMARIZE_DOCUMENT_USER.format(
                chunk_count=len(chunk_summaries),
                filename=filename,
                chunk_summaries_text=chunk_summaries_text,
            ),
        },
    ]

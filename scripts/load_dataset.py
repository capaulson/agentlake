#!/usr/bin/env python3
"""Load the 50-document test dataset into AgentLake.

Uploads all .md files from tests/test_dataset/ through the processing pipeline:
  1. Upload to MinIO
  2. Create File record in PostgreSQL
  3. Extract → Chunk → Summarize (LLM) → Classify (LLM) → Extract Entities (LLM)
  4. Store ProcessedDocument + Chunks + Citations + DiffLog

Uses OpenRouter + Nemotron Super for LLM calls.
Requires: postgres:5433, redis:6379, minio:9000 running.

Usage:
    python scripts/load_dataset.py
"""

import asyncio
import hashlib
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

import httpx
import structlog

structlog.configure(processors=[structlog.dev.ConsoleRenderer()])
log = structlog.get_logger()

# ── Config ──

DATASET_DIR = Path(__file__).parent.parent / "tests" / "test_dataset"
OPENROUTER_API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEY_HERE",
)
LLM_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
DB_URL = "postgresql+asyncpg://agentlake:agentlake_dev_password@localhost:5433/agentlake"
MINIO_ENDPOINT = "localhost:9000"
MINIO_ACCESS_KEY = "agentlake_minio"
MINIO_SECRET_KEY = "agentlake_minio_secret"
MINIO_BUCKET = "agentlake-vault"

# How many docs to process with LLM (rest get fast-path without LLM)
LLM_PROCESS_COUNT = 15  # Process first 15 with full LLM, rest with fast extraction only

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://agentlake.dev",
    "X-Title": "AgentLake",
}


def extract_llm_content(response_json: dict) -> str:
    """Extract content from LLM response, handling reasoning models."""
    message = response_json["choices"][0]["message"]
    content = message.get("content") or ""
    if not content:
        content = message.get("reasoning", "")
    return content


async def llm_call(client: httpx.AsyncClient, messages: list[dict], max_tokens: int = 500, temperature: float = 0.3) -> str:
    """Make an LLM call via OpenRouter."""
    resp = await client.post(f"{OPENROUTER_URL}/chat/completions", json={
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    })
    resp.raise_for_status()
    return extract_llm_content(resp.json())


async def process_document(
    db, storage, registry, chunker, llm_client, file_path: Path, use_llm: bool = True
) -> dict:
    """Process a single document through the full pipeline."""
    from agentlake.models.file import File, FileStatus
    from agentlake.models.document import ProcessedDocument, DocumentChunk, Citation
    from agentlake.models.diff_log import DiffLog, DiffType

    content = file_path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    storage_key = f"{uuid.uuid4()}/{file_path.name}"

    # 1. Upload to MinIO
    await storage.upload_file(storage_key, io.BytesIO(content), len(content), "text/markdown")

    # 2. Create File record
    file_record = File(
        filename=file_path.name,
        original_filename=file_path.name,
        content_type="text/markdown",
        size_bytes=len(content),
        sha256_hash=sha256,
        storage_key=storage_key,
        status=FileStatus.PROCESSING,
        processing_started_at=datetime.now(timezone.utc),
    )
    db.add(file_record)
    await db.flush()

    # 3. Extract + Chunk
    adapter = registry.get_adapter(file_path.name, "text/markdown")
    extracted = adapter.extract(content, file_path.name)
    chunks = chunker.chunk(extracted)

    # 4. Summarize
    chunk_summaries = []
    doc_summary = ""
    category = "reference"
    entities = []
    title = file_path.name.replace(".md", "").replace("-", " ").title()

    if use_llm and llm_client:
        try:
            # Summarize first 5 chunks with LLM
            for i, chunk in enumerate(chunks[:5]):
                summary = await llm_call(llm_client, [
                    {"role": "system", "content": "Summarize this text concisely in 2-3 sentences. Preserve key facts, names, and numbers."},
                    {"role": "user", "content": chunk.content[:2000]},
                ], max_tokens=300)
                chunk_summaries.append(summary)

            # Fast-path remaining chunks
            for chunk in chunks[5:]:
                chunk_summaries.append(chunk.content[:300])

            # Document summary
            combined = "\n\n".join(chunk_summaries[:5])
            doc_summary = await llm_call(llm_client, [
                {"role": "system", "content": "Write a comprehensive 3-4 sentence summary of this document."},
                {"role": "user", "content": combined[:4000]},
            ], max_tokens=300)

            # Classify
            cat_text = await llm_call(llm_client, [
                {"role": "system", "content": "Classify this document into exactly ONE category. Reply with ONLY the category word: technical, business, operational, research, communication, or reference"},
                {"role": "user", "content": doc_summary[:1000]},
            ], max_tokens=20, temperature=0.0)
            for valid in ["technical", "business", "operational", "research", "communication", "reference"]:
                if valid in cat_text.lower():
                    category = valid
                    break

            # Extract entities
            entity_text = await llm_call(llm_client, [
                {"role": "system", "content": "Extract named entities from this text. Return a JSON array of objects with 'name' and 'type' fields. Types: person, organization, product, technology, location, event. Return ONLY valid JSON, no commentary."},
                {"role": "user", "content": doc_summary[:2000]},
            ], max_tokens=500, temperature=0.1)
            try:
                start = entity_text.find("[")
                end = entity_text.rfind("]") + 1
                if start >= 0 and end > start:
                    entities = json.loads(entity_text[start:end])
            except (json.JSONDecodeError, ValueError):
                entities = []

            # Generate title from LLM
            title_text = await llm_call(llm_client, [
                {"role": "system", "content": "Generate a short descriptive title (5-10 words) for this document. Reply with ONLY the title, no quotes or formatting."},
                {"role": "user", "content": doc_summary[:500]},
            ], max_tokens=30, temperature=0.1)
            if title_text and len(title_text.strip()) > 5:
                title = title_text.strip().strip('"').strip("'")[:100]

        except Exception as e:
            log.warning("llm_processing_error", error=str(e), file=file_path.name)
            # Fall back to non-LLM processing
            doc_summary = extracted.full_text[:500]
            chunk_summaries = [c.content[:300] for c in chunks]
    else:
        # Fast path: no LLM
        doc_summary = extracted.full_text[:500]
        chunk_summaries = [c.content[:300] for c in chunks]
        # Guess category from filename
        name = file_path.name.lower()
        if name.startswith("tech"):
            category = "technical"
        elif name.startswith("biz"):
            category = "business"
        elif name.startswith("ops"):
            category = "operational"
        elif name.startswith("research"):
            category = "research"
        elif name.startswith("comms"):
            category = "communication"
        else:
            category = "reference"

    # 5. Assemble markdown with citations
    citations_md = "\n".join(
        f"[{i+1}](/api/v1/vault/files/{file_record.id}/download#chunk={i})"
        for i in range(len(chunks))
    )

    body_markdown = f"""# {title}

{doc_summary}

---

## Detailed Content

{"".join(f"### Section {i+1}\\n\\n{s}\\n\\n" for i, s in enumerate(chunk_summaries))}

---

## Citations

{citations_md}
"""

    frontmatter = {
        "source_file_id": str(file_record.id),
        "title": title,
        "summary": doc_summary[:500],
        "category": category,
        "entities": entities,
        "processing_version": 1,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    # 6. Store ProcessedDocument
    doc = ProcessedDocument(
        source_file_id=file_record.id,
        title=title,
        summary=doc_summary[:2000],
        category=category,
        body_markdown=body_markdown,
        frontmatter=frontmatter,
        entities=entities,
        version=1,
        is_current=True,
        processing_version=1,
    )
    db.add(doc)
    await db.flush()

    # Store chunks
    for i, (chunk, summary) in enumerate(zip(chunks, chunk_summaries)):
        db.add(DocumentChunk(
            document_id=doc.id,
            chunk_index=i,
            content=chunk.content,
            summary=summary[:2000] if summary else None,
            source_locator=chunk.source_locator,
            token_count=chunk.token_count,
            content_hash=chunk.content_hash,
        ))

    # Store citations
    for i, chunk in enumerate(chunks):
        db.add(Citation(
            document_id=doc.id,
            citation_index=i + 1,
            source_file_id=file_record.id,
            chunk_index=i,
            source_locator=chunk.source_locator,
            quote_snippet=chunk.content[:150],
        ))

    # Store diff log
    db.add(DiffLog(
        document_id=doc.id,
        source_file_id=file_record.id,
        diff_type=DiffType.INITIAL_PROCESSING,
        after_text=body_markdown[:5000],
        justification="Initial processing",
        created_by="dataset_loader",
    ))

    # Update file status
    file_record.status = FileStatus.PROCESSED
    file_record.processing_completed_at = datetime.now(timezone.utc)

    return {
        "file_id": str(file_record.id),
        "doc_id": str(doc.id),
        "title": title,
        "category": category,
        "chunks": len(chunks),
        "entities": len(entities),
        "used_llm": use_llm,
    }


async def main():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select, func
    from agentlake.adapters.registry import AdapterRegistry
    from agentlake.services.chunker import SemanticChunker
    from agentlake.services.storage import StorageService
    from agentlake.models.file import File
    from agentlake.models.document import ProcessedDocument, DocumentChunk, Citation
    from agentlake.models.diff_log import DiffLog

    print("\n\033[1m\033[96m" + "=" * 60 + "\033[0m")
    print("\033[1m\033[96m  AgentLake Dataset Loader\033[0m")
    print("\033[1m\033[96m" + "=" * 60 + "\033[0m")
    print(f"  Model:   {LLM_MODEL}")
    print(f"  Dataset: {DATASET_DIR}")
    print(f"  LLM processing: first {LLM_PROCESS_COUNT} docs (rest: fast extraction)")

    # Setup
    engine = create_async_engine(DB_URL, pool_size=5)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    registry = AdapterRegistry()
    registry.auto_discover()

    chunker = SemanticChunker(max_tokens=512, overlap_tokens=32)

    class MinioSettings:
        MINIO_ENDPOINT = MINIO_ENDPOINT
        MINIO_ACCESS_KEY = MINIO_ACCESS_KEY
        MINIO_SECRET_KEY = MINIO_SECRET_KEY
        MINIO_BUCKET = MINIO_BUCKET
        MINIO_SECURE = False

    storage = StorageService(MinioSettings())
    await storage.ensure_bucket()

    # Check what's already loaded
    async with Session() as db:
        existing = await db.scalar(select(func.count()).select_from(File))
        if existing and existing > 0:
            print(f"\n  \033[93m⚠ Found {existing} existing files. Clearing for fresh load...\033[0m")
            await db.execute(DiffLog.__table__.delete())
            await db.execute(Citation.__table__.delete())
            await db.execute(DocumentChunk.__table__.delete())
            await db.execute(ProcessedDocument.__table__.delete())
            await db.execute(File.__table__.delete())
            await db.commit()
            print("  \033[92m✓\033[0m Database cleared")

    # Get all markdown files
    files = sorted(DATASET_DIR.glob("*.md"))
    print(f"\n  Found {len(files)} documents to load\n")

    # Process
    llm_client = httpx.AsyncClient(headers=HEADERS, timeout=120.0)
    results = []
    total_chunks = 0
    total_entities = 0
    total_llm_calls = 0
    start_time = time.time()

    async with Session() as db:
        for i, file_path in enumerate(files):
            use_llm = i < LLM_PROCESS_COUNT
            tag = "\033[96mLLM\033[0m" if use_llm else "\033[90mFAST\033[0m"

            try:
                result = await process_document(
                    db, storage, registry, chunker,
                    llm_client if use_llm else None,
                    file_path, use_llm=use_llm,
                )
                total_chunks += result["chunks"]
                total_entities += result["entities"]
                if use_llm:
                    total_llm_calls += 8  # ~8 LLM calls per doc

                print(f"  [{i+1:2d}/50] [{tag}] \033[92m✓\033[0m {file_path.name}")
                print(f"           {result['category']:13s} | {result['chunks']:2d} chunks | {result['entities']:2d} entities | \"{result['title'][:50]}\"")
                results.append(result)

                # Commit every 5 docs
                if (i + 1) % 5 == 0:
                    await db.commit()
                    print(f"           \033[90m--- committed {i+1} docs ---\033[0m")

            except Exception as e:
                print(f"  [{i+1:2d}/50] [{tag}] \033[91m✗\033[0m {file_path.name}: {e}")
                await db.rollback()

            # Rate limit for LLM calls
            if use_llm:
                await asyncio.sleep(0.5)

        # Final commit
        await db.commit()

    await llm_client.aclose()
    elapsed = time.time() - start_time

    # Summary
    async with Session() as db:
        file_count = await db.scalar(select(func.count()).select_from(File))
        doc_count = await db.scalar(select(func.count()).select_from(ProcessedDocument))
        chunk_count = await db.scalar(select(func.count()).select_from(DocumentChunk))
        citation_count = await db.scalar(select(func.count()).select_from(Citation))
        diff_count = await db.scalar(select(func.count()).select_from(DiffLog))

    await engine.dispose()

    print(f"\n\033[1m\033[96m" + "=" * 60 + "\033[0m")
    print(f"\033[1m\033[96m  Load Complete!\033[0m")
    print(f"\033[1m\033[96m" + "=" * 60 + "\033[0m")
    print(f"  Time:              {elapsed:.1f}s")
    print(f"  Documents loaded:  {len(results)}/50")
    print(f"  LLM processed:     {sum(1 for r in results if r['used_llm'])}")
    print(f"  Fast processed:    {sum(1 for r in results if not r['used_llm'])}")
    print(f"\n  \033[1mDatabase counts:\033[0m")
    print(f"    files:               {file_count}")
    print(f"    processed_documents: {doc_count}")
    print(f"    document_chunks:     {chunk_count}")
    print(f"    citations:           {citation_count}")
    print(f"    diff_logs:           {diff_count}")
    print(f"  Total chunks:      {total_chunks}")
    print(f"  Total entities:    {total_entities}")
    print(f"  Est. LLM calls:    ~{total_llm_calls}")

    # Category breakdown
    cats = {}
    for r in results:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    print(f"\n  \033[1mBy category:\033[0m")
    for cat, count in sorted(cats.items()):
        print(f"    {cat:15s}: {count}")


if __name__ == "__main__":
    asyncio.run(main())

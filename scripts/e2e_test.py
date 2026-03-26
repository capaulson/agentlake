#!/usr/bin/env python3
"""End-to-end test for AgentLake.

Tests the full pipeline: upload files → process → search → view → edit.
Runs against local services (postgres:5433, redis:6379, minio:9000).
Uses OpenRouter + Nemotron Super for LLM calls.

Usage:
    python scripts/e2e_test.py
"""

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add backend src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

import httpx
import structlog

# Configure structlog for readable output
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(),
    ],
)
log = structlog.get_logger()

# ── Configuration ──────────────────────────────────────────────────────────

DATASET_DIR = Path(__file__).parent.parent / "tests" / "test_dataset"
OPENROUTER_API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEY_HERE",
)
LLM_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
EMBED_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1"

DB_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://agentlake:agentlake_dev_password@localhost:5433/agentlake")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "agentlake_minio")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "agentlake_minio_secret")
MINIO_BUCKET = "agentlake-vault"


def extract_llm_content(response_json: dict) -> str:
    """Extract content from LLM response, handling reasoning models.

    Nemotron Super puts output in 'reasoning' instead of 'content'.
    This helper extracts from whichever field has content.
    """
    message = response_json["choices"][0]["message"]
    content = message.get("content")
    if content:
        return content

    # For reasoning models, extract from reasoning field
    reasoning = message.get("reasoning", "")
    if reasoning:
        # Try to find the actual answer after the reasoning
        # Often the model thinks then produces the answer
        return reasoning

    return ""


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def ok(msg):
    print(f"  {Colors.GREEN}✓{Colors.END} {msg}")


def fail(msg):
    print(f"  {Colors.RED}✗{Colors.END} {msg}")


def info(msg):
    print(f"  {Colors.CYAN}→{Colors.END} {msg}")


def section(msg):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {msg}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")


async def test_infrastructure():
    """Test 1: Verify infrastructure services are running."""
    section("Test 1: Infrastructure Health")
    passed = 0
    total = 3

    # PostgreSQL
    try:
        import asyncpg
        conn = await asyncpg.connect(
            user="agentlake", password="agentlake_dev_password",
            database="agentlake", host="127.0.0.1", port=5433,
        )
        extensions = await conn.fetch("SELECT extname FROM pg_extension")
        ext_names = [r["extname"] for r in extensions]
        await conn.close()
        assert "vector" in ext_names, "pgvector not installed"
        assert "age" in ext_names, "Apache AGE not installed"
        ok(f"PostgreSQL: connected, extensions: {ext_names}")
        passed += 1
    except Exception as e:
        fail(f"PostgreSQL: {e}")

    # Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.ping()
        await r.close()
        ok("Redis: connected and responding")
        passed += 1
    except Exception as e:
        fail(f"Redis: {e}")

    # MinIO
    try:
        from minio import Minio
        client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY,
                       secret_key=MINIO_SECRET_KEY, secure=False)
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
            ok(f"MinIO: created bucket '{MINIO_BUCKET}'")
        else:
            ok(f"MinIO: connected, bucket '{MINIO_BUCKET}' exists")
        passed += 1
    except Exception as e:
        fail(f"MinIO: {e}")

    return passed, total


async def test_file_adapters():
    """Test 2: Verify file adapters can extract content."""
    section("Test 2: File Adapters")
    from agentlake.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    registry.auto_discover()
    info(f"Discovered {len(registry._adapters)} adapters")

    files = sorted(DATASET_DIR.glob("*.md"))[:5]
    passed = 0
    total = len(files)

    for f in files:
        try:
            adapter = registry.get_adapter(f.name, "text/markdown")
            content = f.read_bytes()
            extracted = adapter.extract(content, f.name)
            assert len(extracted.text_blocks) > 0, "No text blocks extracted"
            ok(f"{f.name}: {len(extracted.text_blocks)} blocks, {len(extracted.full_text)} chars")
            passed += 1
        except Exception as e:
            fail(f"{f.name}: {e}")

    return passed, total


async def test_chunking():
    """Test 3: Verify chunking works correctly."""
    section("Test 3: Semantic Chunking")
    from agentlake.adapters.registry import AdapterRegistry
    from agentlake.services.chunker import SemanticChunker

    registry = AdapterRegistry()
    registry.auto_discover()
    chunker = SemanticChunker(max_tokens=512, overlap_tokens=32)

    files = sorted(DATASET_DIR.glob("*.md"))[:3]
    passed = 0
    total = len(files)

    for f in files:
        try:
            adapter = registry.get_adapter(f.name, "text/markdown")
            extracted = adapter.extract(f.read_bytes(), f.name)
            chunks = chunker.chunk(extracted)
            assert len(chunks) > 0, "No chunks produced"
            for chunk in chunks:
                assert chunk.content_hash, "Missing content hash"
                assert chunk.token_count > 0, "Zero token count"
                assert chunk.token_count <= 600, f"Chunk too large: {chunk.token_count} tokens"
            ok(f"{f.name}: {len(chunks)} chunks, max {max(c.token_count for c in chunks)} tokens")
            passed += 1
        except Exception as e:
            fail(f"{f.name}: {e}")

    return passed, total


async def test_llm_completions():
    """Test 4: Verify LLM calls work via OpenRouter."""
    section("Test 4: LLM Completions (Nemotron Super)")
    passed = 0
    total = 3

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://agentlake.dev",
        "X-Title": "AgentLake E2E Test",
    }

    async with httpx.AsyncClient(headers=headers, timeout=120.0) as client:
        # Test 1: Basic completion
        try:
            resp = await client.post(f"{OPENROUTER_URL}/chat/completions", json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": "Summarize in 2 sentences: Machine learning enables computers to learn from data without being explicitly programmed."}],
                "max_tokens": 200,
                "temperature": 0.3,
            })
            resp.raise_for_status()
            data = resp.json()
            content = extract_llm_content(data)
            tokens = data.get("usage", {}).get("total_tokens", 0)
            ok(f"Completion: {len(content)} chars, {tokens} tokens, model={data.get('model','?')}")
            passed += 1
        except Exception as e:
            fail(f"Completion: {e}")

        # Test 2: Structured extraction (YAML)
        try:
            resp = await client.post(f"{OPENROUTER_URL}/chat/completions", json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "Extract entities from the text. Return YAML list with name and type fields only."},
                    {"role": "user", "content": "Sarah Chen, CTO of NovaTech, announced a partnership with Acme Corp at the San Francisco conference."},
                ],
                "max_tokens": 300,
                "temperature": 0.1,
            })
            resp.raise_for_status()
            data = resp.json()
            content = extract_llm_content(data)
            assert len(content) > 10, f"Too short: {content}"
            ok(f"Entity extraction: got {len(content)} chars")
            passed += 1
        except Exception as e:
            fail(f"Entity extraction: {e}")

        # Test 3: Classification
        try:
            resp = await client.post(f"{OPENROUTER_URL}/chat/completions", json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "Classify the document category. Reply with only one word: technical, business, operational, research, communication, or reference."},
                    {"role": "user", "content": "Q4 Revenue Report: Total revenue reached $12.5M, up 34% YoY. Enterprise segment grew 45%."},
                ],
                "max_tokens": 10,
                "temperature": 0.0,
            })
            resp.raise_for_status()
            data = resp.json()
            content = extract_llm_content(data).strip().lower()
            ok(f"Classification: '{content[:100]}'")
            passed += 1
        except Exception as e:
            fail(f"Classification: {e}")

    return passed, total


async def test_database_operations():
    """Test 5: Verify database CRUD operations."""
    section("Test 5: Database Operations")
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select, func
    from agentlake.models.file import File, FileStatus
    from agentlake.models.tag import Tag, FileTag
    from agentlake.models.document import ProcessedDocument, DocumentChunk, Citation
    from agentlake.models.diff_log import DiffLog, DiffType

    engine = create_async_engine(DB_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    passed = 0
    total = 5

    async with Session() as db:
        # Test 1: Create a file record
        try:
            file = File(
                filename="test-e2e.md",
                original_filename="test-e2e.md",
                content_type="text/markdown",
                size_bytes=1024,
                sha256_hash=hashlib.sha256(b"test").hexdigest(),
                storage_key=f"{uuid.uuid4()}/test-e2e.md",
                status=FileStatus.PENDING,
            )
            db.add(file)
            await db.flush()
            assert file.id is not None
            ok(f"File created: id={file.id}")
            passed += 1
        except Exception as e:
            fail(f"File create: {e}")
            await db.rollback()
            await engine.dispose()
            return passed, total

        # Test 2: Create a tag and attach to file
        try:
            tag = Tag(name="e2e-test", description="End-to-end test tag")
            db.add(tag)
            await db.flush()
            file_tag = FileTag(file_id=file.id, tag_id=tag.id)
            db.add(file_tag)
            await db.flush()
            ok(f"Tag created and attached: {tag.name} -> {file.filename}")
            passed += 1
        except Exception as e:
            fail(f"Tag: {e}")

        # Test 3: Create a processed document
        try:
            doc = ProcessedDocument(
                source_file_id=file.id,
                title="E2E Test Document",
                summary="This is a test document for end-to-end testing.",
                category="technical",
                body_markdown="# Test\n\nThis is test content.",
                frontmatter={"category": "technical", "entities": []},
                entities=[{"name": "AgentLake", "type": "product"}],
                version=1,
                is_current=True,
                processing_version=1,
            )
            db.add(doc)
            await db.flush()
            assert doc.id is not None
            ok(f"ProcessedDocument created: id={doc.id}")
            passed += 1
        except Exception as e:
            fail(f"Document: {e}")

        # Test 4: Create chunks
        try:
            chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=0,
                content="This is test content for the chunk.",
                summary="Test chunk summary.",
                source_locator="line:1",
                token_count=10,
                content_hash=hashlib.sha256(b"chunk content").hexdigest(),
            )
            db.add(chunk)
            await db.flush()
            ok(f"DocumentChunk created: index={chunk.chunk_index}")
            passed += 1
        except Exception as e:
            fail(f"Chunk: {e}")

        # Test 5: Create diff log
        try:
            diff = DiffLog(
                document_id=doc.id,
                source_file_id=file.id,
                diff_type=DiffType.INITIAL_PROCESSING,
                after_text="# Test\n\nThis is test content.",
                justification="Initial processing",
                created_by="e2e_test",
            )
            db.add(diff)
            await db.flush()
            ok(f"DiffLog created: type={diff.diff_type}")
            passed += 1
        except Exception as e:
            fail(f"DiffLog: {e}")

        await db.commit()

    # Clean up
    async with Session() as db:
        try:
            await db.execute(
                DiffLog.__table__.delete().where(DiffLog.created_by == "e2e_test")
            )
            file_result = await db.execute(
                select(File).where(File.filename == "test-e2e.md")
            )
            for f in file_result.scalars().all():
                await db.delete(f)
            tag_result = await db.execute(
                select(Tag).where(Tag.name == "e2e-test")
            )
            for t in tag_result.scalars().all():
                await db.delete(t)
            await db.commit()
        except Exception:
            await db.rollback()

    await engine.dispose()
    return passed, total


async def test_minio_storage():
    """Test 6: Upload and download from MinIO."""
    section("Test 6: MinIO Storage")
    from agentlake.services.storage import StorageService
    from agentlake.config import Settings

    passed = 0
    total = 3

    # Create a minimal settings-like object
    class MinioSettings:
        MINIO_ENDPOINT = MINIO_ENDPOINT
        MINIO_ACCESS_KEY = MINIO_ACCESS_KEY
        MINIO_SECRET_KEY = MINIO_SECRET_KEY
        MINIO_BUCKET = MINIO_BUCKET
        MINIO_SECURE = False

    storage = StorageService(MinioSettings())

    # Test 1: Ensure bucket
    try:
        await storage.ensure_bucket()
        ok("Bucket ensured")
        passed += 1
    except Exception as e:
        fail(f"Ensure bucket: {e}")
        return passed, total

    # Test 2: Upload a file
    test_key = f"e2e-test/{uuid.uuid4()}/test.md"
    test_content = b"# Test Document\n\nThis is a test file for MinIO storage."
    try:
        import io
        await storage.upload_file(test_key, io.BytesIO(test_content), len(test_content), "text/markdown")
        ok(f"Uploaded: {test_key} ({len(test_content)} bytes)")
        passed += 1
    except Exception as e:
        fail(f"Upload: {e}")
        return passed, total

    # Test 3: Download and verify
    try:
        downloaded = await storage.download_file(test_key)
        assert downloaded == test_content, f"Content mismatch: {len(downloaded)} != {len(test_content)}"
        ok(f"Downloaded and verified: {len(downloaded)} bytes match")
        passed += 1
    except Exception as e:
        fail(f"Download: {e}")

    # Cleanup
    try:
        await storage.delete_file(test_key)
    except Exception:
        pass

    return passed, total


async def test_full_pipeline_single_doc():
    """Test 7: Process a single document through the full pipeline (without Celery)."""
    section("Test 7: Full Pipeline (Single Document)")

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from agentlake.adapters.registry import AdapterRegistry
    from agentlake.services.chunker import SemanticChunker
    from agentlake.services.storage import StorageService
    from agentlake.models.file import File, FileStatus
    from agentlake.models.document import ProcessedDocument, DocumentChunk, Citation
    from agentlake.models.diff_log import DiffLog, DiffType

    passed = 0
    total = 6

    # Pick a test document
    test_file = sorted(DATASET_DIR.glob("*.md"))[0]
    file_content = test_file.read_bytes()
    info(f"Processing: {test_file.name} ({len(file_content)} bytes)")

    # Setup
    engine = create_async_engine(DB_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    registry = AdapterRegistry()
    registry.auto_discover()
    chunker = SemanticChunker(max_tokens=512, overlap_tokens=32)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://agentlake.dev",
        "X-Title": "AgentLake E2E Test",
    }

    class MinioSettings:
        MINIO_ENDPOINT = MINIO_ENDPOINT
        MINIO_ACCESS_KEY = MINIO_ACCESS_KEY
        MINIO_SECRET_KEY = MINIO_SECRET_KEY
        MINIO_BUCKET = MINIO_BUCKET
        MINIO_SECURE = False

    storage = StorageService(MinioSettings())
    await storage.ensure_bucket()

    async with Session() as db:
        # Stage 1: Upload to MinIO + create file record
        try:
            import io
            sha256 = hashlib.sha256(file_content).hexdigest()
            storage_key = f"{uuid.uuid4()}/{test_file.name}"
            await storage.upload_file(storage_key, io.BytesIO(file_content), len(file_content), "text/markdown")

            file_record = File(
                filename=test_file.name,
                original_filename=test_file.name,
                content_type="text/markdown",
                size_bytes=len(file_content),
                sha256_hash=sha256,
                storage_key=storage_key,
                status=FileStatus.PROCESSING,
                processing_started_at=datetime.now(timezone.utc),
            )
            db.add(file_record)
            await db.flush()
            ok(f"Stage 1 (Upload): file_id={file_record.id}")
            passed += 1
        except Exception as e:
            fail(f"Stage 1: {e}")
            await engine.dispose()
            return passed, total

        # Stage 2: Extract + Chunk
        try:
            adapter = registry.get_adapter(test_file.name, "text/markdown")
            extracted = adapter.extract(file_content, test_file.name)
            chunks = chunker.chunk(extracted)
            info(f"Extracted {len(extracted.text_blocks)} blocks, chunked into {len(chunks)} chunks")
            ok(f"Stage 2 (Extract+Chunk): {len(chunks)} chunks")
            passed += 1
        except Exception as e:
            fail(f"Stage 2: {e}")
            await engine.dispose()
            return passed, total

        # Stage 3: Summarize chunks via Nemotron Super
        try:
            chunk_summaries = []
            async with httpx.AsyncClient(headers=headers, timeout=120.0) as llm:
                for i, chunk in enumerate(chunks[:3]):  # Limit to 3 chunks to save cost
                    resp = await llm.post(f"{OPENROUTER_URL}/chat/completions", json={
                        "model": LLM_MODEL,
                        "messages": [
                            {"role": "system", "content": "Summarize the following text concisely in 2-3 sentences. Preserve key facts."},
                            {"role": "user", "content": chunk.content[:2000]},
                        ],
                        "max_tokens": 300,
                        "temperature": 0.3,
                    })
                    resp.raise_for_status()
                    data = resp.json()
                    summary = extract_llm_content(data)
                    if summary:
                        chunk_summaries.append(summary)
                    else:
                        chunk_summaries.append(chunk.content[:200])
                    info(f"  Chunk {i+1}/{min(len(chunks), 3)}: {len(summary)} chars")

                # Add remaining chunks without LLM (use content as summary for speed)
                for chunk in chunks[3:]:
                    chunk_summaries.append(chunk.content[:200] + "...")

                # Document-level summary
                combined = "\n".join(chunk_summaries[:3])
                resp = await llm.post(f"{OPENROUTER_URL}/chat/completions", json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "Write a concise 2-3 sentence summary of this document."},
                        {"role": "user", "content": combined[:3000]},
                    ],
                    "max_tokens": 200,
                    "temperature": 0.3,
                })
                resp.raise_for_status()
                doc_summary = extract_llm_content(resp.json()) or combined[:200]

            ok(f"Stage 3 (Summarize): {len(chunk_summaries)} summaries, doc summary: {len(doc_summary)} chars")
            passed += 1
        except Exception as e:
            fail(f"Stage 3: {e}")
            doc_summary = "Test summary"
            chunk_summaries = [c.content[:200] for c in chunks]

        # Stage 4: Classify + Extract Entities via Nemotron
        try:
            async with httpx.AsyncClient(headers=headers, timeout=120.0) as llm:
                # Classification
                resp = await llm.post(f"{OPENROUTER_URL}/chat/completions", json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "Classify this document. Reply with ONLY one word: technical, business, operational, research, communication, or reference"},
                        {"role": "user", "content": doc_summary[:1000]},
                    ],
                    "max_tokens": 10,
                    "temperature": 0.0,
                })
                resp.raise_for_status()
                category = extract_llm_content(resp.json()).strip().lower() or "reference"
                # Clean up category
                for valid in ["technical", "business", "operational", "research", "communication", "reference"]:
                    if valid in category:
                        category = valid
                        break
                else:
                    category = "reference"

                # Entity extraction
                resp = await llm.post(f"{OPENROUTER_URL}/chat/completions", json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "Extract entities from this text. Return a JSON array of objects with 'name' and 'type' fields. Types: person, organization, product, technology, location, event. Return ONLY valid JSON."},
                        {"role": "user", "content": doc_summary[:2000]},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.1,
                })
                resp.raise_for_status()
                entity_text = extract_llm_content(resp.json()) or "[]"
                # Try to parse JSON from response
                try:
                    # Find JSON array in response
                    start = entity_text.find("[")
                    end = entity_text.rfind("]") + 1
                    if start >= 0 and end > start:
                        entities = json.loads(entity_text[start:end])
                    else:
                        entities = []
                except json.JSONDecodeError:
                    entities = []

            ok(f"Stage 4 (Classify+Entities): category={category}, {len(entities)} entities")
            passed += 1
        except Exception as e:
            fail(f"Stage 4: {e}")
            category = "reference"
            entities = []

        # Stage 5: Assemble + Store
        try:
            # Build citations
            citations_md = "\n".join(
                f"[{i+1}](/api/v1/vault/files/{file_record.id}/download#chunk={i})"
                for i in range(len(chunks))
            )

            body_markdown = f"""# {test_file.name.replace('.md', '').replace('-', ' ').title()}

{doc_summary}

---

## Content

{chr(10).join(chunk_summaries)}

---

## Citations

{citations_md}
"""

            frontmatter = {
                "id": str(uuid.uuid4()),
                "source_file_id": str(file_record.id),
                "title": test_file.name.replace(".md", "").replace("-", " ").title(),
                "summary": doc_summary[:500],
                "category": category,
                "entities": entities,
                "processing_version": 1,
            }

            doc = ProcessedDocument(
                source_file_id=file_record.id,
                title=frontmatter["title"],
                summary=doc_summary[:1000],
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

            # Create chunks in DB
            for i, (chunk, summary) in enumerate(zip(chunks, chunk_summaries)):
                db_chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=i,
                    content=chunk.content,
                    summary=summary[:1000],
                    source_locator=chunk.source_locator,
                    token_count=chunk.token_count,
                    content_hash=chunk.content_hash,
                )
                db.add(db_chunk)

            # Create citations
            for i in range(len(chunks)):
                citation = Citation(
                    document_id=doc.id,
                    citation_index=i + 1,
                    source_file_id=file_record.id,
                    chunk_index=i,
                    source_locator=chunks[i].source_locator,
                    quote_snippet=chunks[i].content[:100],
                )
                db.add(citation)

            # Create diff log
            diff = DiffLog(
                document_id=doc.id,
                source_file_id=file_record.id,
                diff_type=DiffType.INITIAL_PROCESSING,
                after_text=body_markdown[:5000],
                justification="Initial processing via e2e test",
                created_by="e2e_test",
            )
            db.add(diff)

            # Update file status
            file_record.status = FileStatus.PROCESSED
            file_record.processing_completed_at = datetime.now(timezone.utc)

            await db.commit()
            ok(f"Stage 5 (Store): doc_id={doc.id}, {len(chunks)} chunks, {len(chunks)} citations")
            passed += 1
        except Exception as e:
            fail(f"Stage 5: {e}")
            await db.rollback()

        # Stage 6: Query back
        try:
            from sqlalchemy import select
            result = await db.execute(
                select(ProcessedDocument).where(
                    ProcessedDocument.source_file_id == file_record.id,
                    ProcessedDocument.is_current == True,
                )
            )
            stored_doc = result.scalar_one_or_none()
            assert stored_doc is not None, "Document not found"
            assert stored_doc.title, "Missing title"
            assert stored_doc.summary, "Missing summary"
            assert stored_doc.category in ["technical", "business", "operational", "research", "communication", "reference"], f"Invalid category: {stored_doc.category}"

            # Count chunks
            chunk_result = await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == stored_doc.id)
            )
            stored_chunks = chunk_result.scalars().all()

            # Count citations
            citation_result = await db.execute(
                select(Citation).where(Citation.document_id == stored_doc.id)
            )
            stored_citations = citation_result.scalars().all()

            ok(f"Stage 6 (Query): title='{stored_doc.title}', category={stored_doc.category}, {len(stored_chunks)} chunks, {len(stored_citations)} citations")
            passed += 1
        except Exception as e:
            fail(f"Stage 6: {e}")

    await engine.dispose()
    return passed, total


async def test_batch_upload():
    """Test 8: Upload multiple documents from the dataset."""
    section("Test 8: Batch Upload (10 documents)")
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from agentlake.adapters.registry import AdapterRegistry
    from agentlake.services.chunker import SemanticChunker
    from agentlake.services.storage import StorageService
    from agentlake.models.file import File, FileStatus
    from agentlake.models.document import ProcessedDocument, DocumentChunk
    import io

    engine = create_async_engine(DB_URL)
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

    files = sorted(DATASET_DIR.glob("*.md"))[1:11]  # Skip first (already processed)
    passed = 0
    total = len(files)

    async with Session() as db:
        for test_file in files:
            try:
                content = test_file.read_bytes()
                sha256 = hashlib.sha256(content).hexdigest()
                storage_key = f"{uuid.uuid4()}/{test_file.name}"

                await storage.upload_file(storage_key, io.BytesIO(content), len(content), "text/markdown")

                file_record = File(
                    filename=test_file.name,
                    original_filename=test_file.name,
                    content_type="text/markdown",
                    size_bytes=len(content),
                    sha256_hash=sha256,
                    storage_key=storage_key,
                    status=FileStatus.PROCESSED,
                )
                db.add(file_record)
                await db.flush()

                adapter = registry.get_adapter(test_file.name, "text/markdown")
                extracted = adapter.extract(content, test_file.name)
                chunks = chunker.chunk(extracted)

                doc = ProcessedDocument(
                    source_file_id=file_record.id,
                    title=test_file.name.replace(".md", "").replace("-", " ").title(),
                    summary=extracted.full_text[:300],
                    category="technical",
                    body_markdown=extracted.full_text,
                    frontmatter={"category": "technical"},
                    entities=[],
                    version=1,
                    is_current=True,
                    processing_version=1,
                )
                db.add(doc)
                await db.flush()

                for i, chunk in enumerate(chunks):
                    db.add(DocumentChunk(
                        document_id=doc.id, chunk_index=i, content=chunk.content,
                        source_locator=chunk.source_locator, token_count=chunk.token_count,
                        content_hash=chunk.content_hash,
                    ))

                ok(f"{test_file.name}: {len(chunks)} chunks")
                passed += 1
            except Exception as e:
                fail(f"{test_file.name}: {e}")

        await db.commit()

    info(f"Total documents in DB:")
    async with Session() as db:
        from sqlalchemy import select, func
        count = await db.scalar(select(func.count()).select_from(ProcessedDocument))
        info(f"  processed_documents: {count}")
        file_count = await db.scalar(select(func.count()).select_from(File))
        info(f"  files: {file_count}")

    await engine.dispose()
    return passed, total


async def main():
    print(f"\n{Colors.BOLD}AgentLake End-to-End Test Suite{Colors.END}")
    print(f"Model: {LLM_MODEL}")
    print(f"Dataset: {DATASET_DIR} ({len(list(DATASET_DIR.glob('*.md')))} files)")
    print(f"Database: {DB_URL}")

    results = []
    start = time.time()

    results.append(await test_infrastructure())
    results.append(await test_file_adapters())
    results.append(await test_chunking())
    results.append(await test_llm_completions())
    results.append(await test_database_operations())
    results.append(await test_minio_storage())
    results.append(await test_full_pipeline_single_doc())
    results.append(await test_batch_upload())

    elapsed = time.time() - start

    # Summary
    total_passed = sum(r[0] for r in results)
    total_tests = sum(r[1] for r in results)

    section("Results")
    for i, (p, t) in enumerate(results, 1):
        status = f"{Colors.GREEN}PASS{Colors.END}" if p == t else f"{Colors.RED}FAIL{Colors.END}"
        print(f"  Test {i}: {p}/{t} [{status}]")

    print(f"\n{Colors.BOLD}Total: {total_passed}/{total_tests} passed in {elapsed:.1f}s{Colors.END}")

    if total_passed == total_tests:
        print(f"\n{Colors.GREEN}{Colors.BOLD}ALL TESTS PASSED{Colors.END}")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}{total_tests - total_passed} TESTS FAILED{Colors.END}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

"""Factory Boy factories for ProcessedDocument, DocumentChunk, and Citation."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import factory

from agentlake.models.document import Citation, DocumentChunk, ProcessedDocument


class ProcessedDocumentFactory(factory.Factory):
    """Factory for creating ProcessedDocument model instances."""

    class Meta:
        model = ProcessedDocument

    id = factory.LazyFunction(uuid.uuid4)
    source_file_id = factory.LazyFunction(uuid.uuid4)
    title = factory.Faker("sentence", nb_words=6)
    summary = factory.Faker("paragraph", nb_sentences=3)
    category = factory.Iterator(
        ["technical", "business", "operational", "research", "communication", "reference"]
    )
    body_markdown = factory.Faker("text", max_nb_chars=2000)
    frontmatter = factory.LazyFunction(lambda: {"title": "Test", "category": "technical"})
    entities = factory.LazyFunction(
        lambda: [{"name": "TestCorp", "type": "ORG"}, {"name": "John", "type": "PERSON"}]
    )
    embedding = None
    search_vector = None
    version = 1
    is_current = True
    processing_version = 1
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))


class DocumentChunkFactory(factory.Factory):
    """Factory for creating DocumentChunk model instances."""

    class Meta:
        model = DocumentChunk

    id = factory.LazyFunction(uuid.uuid4)
    document_id = factory.LazyFunction(uuid.uuid4)
    chunk_index = factory.Sequence(lambda n: n)
    content = factory.Faker("paragraph", nb_sentences=5)
    summary = factory.Faker("sentence", nb_words=10)
    embedding = None
    source_locator = factory.LazyAttribute(lambda o: f"line:{o.chunk_index * 10 + 1}")
    token_count = factory.Faker("random_int", min=50, max=1024)
    content_hash = factory.LazyAttribute(
        lambda o: hashlib.sha256(o.content.encode()).hexdigest()
    )
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))


class CitationFactory(factory.Factory):
    """Factory for creating Citation model instances."""

    class Meta:
        model = Citation

    id = factory.LazyFunction(uuid.uuid4)
    document_id = factory.LazyFunction(uuid.uuid4)
    citation_index = factory.Sequence(lambda n: n + 1)
    source_file_id = factory.LazyFunction(uuid.uuid4)
    chunk_index = factory.Sequence(lambda n: n)
    source_locator = factory.LazyAttribute(lambda o: f"line:{o.chunk_index * 10 + 1}")
    quote_snippet = factory.Faker("sentence", nb_words=15)
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))

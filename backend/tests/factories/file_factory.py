"""Factory Boy factories for File and related models."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import factory

from agentlake.models.api_key import ApiKey
from agentlake.models.file import File, FileStatus
from agentlake.models.tag import FileTag, Tag


class FileFactory(factory.Factory):
    """Factory for creating File model instances."""

    class Meta:
        model = File

    id = factory.LazyFunction(uuid.uuid4)
    filename = factory.Faker("file_name")
    original_filename = factory.LazyAttribute(lambda o: o.filename)
    content_type = factory.Iterator(
        ["text/plain", "application/pdf", "text/csv", "text/markdown"]
    )
    size_bytes = factory.Faker("random_int", min=100, max=1_000_000)
    sha256_hash = factory.LazyFunction(
        lambda: hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    )
    storage_key = factory.LazyAttribute(lambda o: f"{o.id}/{o.filename}")
    uploaded_by = factory.Faker("user_name")
    status = FileStatus.PENDING.value
    error_message = None
    deleted_at = None
    processing_started_at = None
    processing_completed_at = None
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))


class ProcessedFileFactory(FileFactory):
    """Factory for File instances that have been successfully processed."""

    status = FileStatus.PROCESSED.value
    processing_started_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    processing_completed_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))


class TagFactory(factory.Factory):
    """Factory for creating Tag model instances."""

    class Meta:
        model = Tag

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"tag-{n}")
    description = factory.Faker("sentence")
    is_system = False
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))


class ApiKeyFactory(factory.Factory):
    """Factory for creating ApiKey model instances."""

    class Meta:
        model = ApiKey

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Faker("user_name")
    key_hash = factory.LazyFunction(
        lambda: hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    )
    role = "editor"
    is_active = True
    description = factory.Faker("sentence")
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))

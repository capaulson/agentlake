"""Object storage service wrapping MinIO operations.

MinIO's Python SDK is synchronous, so every I/O call is wrapped with
``asyncio.to_thread`` to avoid blocking the async event loop.
"""

from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from typing import BinaryIO, Generator

import structlog
from minio import Minio
from minio.error import S3Error

from agentlake.config import Settings

logger = structlog.get_logger(__name__)


class StorageService:
    """Async-friendly wrapper around the MinIO Python client.

    Args:
        settings: Application settings containing MinIO connection details.
    """

    def __init__(self, settings: Settings) -> None:
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET
        self._log = logger.bind(service="storage", bucket=self.bucket)

    # ── Bucket management ────────────────────────────────────────────────

    async def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not already exist."""
        exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self.bucket)
            self._log.info("bucket_created", bucket=self.bucket)
        else:
            self._log.debug("bucket_already_exists", bucket=self.bucket)

    # ── Upload / Download / Delete ───────────────────────────────────────

    async def upload_file(
        self,
        storage_key: str,
        data: BinaryIO,
        size: int,
        content_type: str,
    ) -> str:
        """Upload a file to MinIO.

        Args:
            storage_key: Object key (path) within the bucket.
            data: Readable binary stream of file content.
            size: Size of the data in bytes.
            content_type: MIME type of the file.

        Returns:
            The ``storage_key`` that was written.

        Raises:
            S3Error: On MinIO communication failure.
        """
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            storage_key,
            data,
            size,
            content_type=content_type,
        )
        self._log.info("file_uploaded", storage_key=storage_key, size=size)
        return storage_key

    async def download_file(self, storage_key: str) -> bytes:
        """Download a file from MinIO and return its contents as bytes.

        Args:
            storage_key: Object key within the bucket.

        Returns:
            Raw file bytes.

        Raises:
            S3Error: If the object does not exist or cannot be read.
        """
        response = None
        try:
            response = await asyncio.to_thread(
                self.client.get_object, self.bucket, storage_key
            )
            data = await asyncio.to_thread(response.read)
            return data
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    async def download_file_stream(self, storage_key: str) -> Generator[bytes, None, None]:
        """Stream a file from MinIO in chunks.

        Args:
            storage_key: Object key within the bucket.

        Yields:
            Chunks of file data (default ~32 KiB each).

        Raises:
            S3Error: If the object does not exist or cannot be read.
        """
        response = None
        try:
            response = await asyncio.to_thread(
                self.client.get_object, self.bucket, storage_key
            )
            for chunk in response.stream(32 * 1024):
                yield chunk
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    async def delete_file(self, storage_key: str) -> None:
        """Delete a file from MinIO.

        Args:
            storage_key: Object key within the bucket.

        Raises:
            S3Error: On MinIO communication failure.
        """
        await asyncio.to_thread(
            self.client.remove_object, self.bucket, storage_key
        )
        self._log.info("file_deleted", storage_key=storage_key)

    async def get_presigned_url(
        self,
        storage_key: str,
        expires: timedelta = timedelta(hours=1),
    ) -> str:
        """Generate a presigned download URL for a stored file.

        Args:
            storage_key: Object key within the bucket.
            expires: How long the URL remains valid.

        Returns:
            Presigned URL string.
        """
        url: str = await asyncio.to_thread(
            self.client.presigned_get_object,
            self.bucket,
            storage_key,
            expires=expires,
        )
        self._log.debug("presigned_url_generated", storage_key=storage_key)
        return url

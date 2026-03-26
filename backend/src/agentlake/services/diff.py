"""Diff service — creates and queries audit trail entries for all document mutations."""

from __future__ import annotations

import difflib
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.models.diff_log import DiffLog, DiffType

logger = structlog.get_logger(__name__)


class DiffService:
    """Service for creating and querying diff log entries.

    Critical invariant: every edit (human or automated) produces a
    DiffLog entry.  There are no silent mutations.

    Also provides static utility methods for computing text diffs
    and similarity.

    Args:
        db: Async SQLAlchemy session.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Create Methods ────────────────────────────────────────────────────

    async def create_initial_diff(
        self,
        document_id: uuid.UUID,
        source_file_id: uuid.UUID,
        content: str,
        justification: str = "Initial processing",
    ) -> DiffLog:
        """Record the initial processing of a document.

        Args:
            document_id: ID of the newly created ProcessedDocument.
            source_file_id: ID of the source File.
            content: The full processed markdown content.
            justification: Reason for the processing.

        Returns:
            The created DiffLog entry.
        """
        diff = DiffLog(
            document_id=document_id,
            source_file_id=source_file_id,
            diff_type=DiffType.INITIAL_PROCESSING.value,
            before_text=None,
            after_text=content,
            justification=justification,
            created_by="system",
        )
        self.db.add(diff)
        await self.db.flush()

        logger.info(
            "diff_initial_created",
            diff_id=str(diff.id),
            document_id=str(document_id),
            source_file_id=str(source_file_id),
        )
        return diff

    async def create_edit_diff(
        self,
        document_id: uuid.UUID,
        source_file_id: uuid.UUID,
        before_text: str,
        after_text: str,
        justification: str,
        created_by: str,
        *,
        diff_type: DiffType = DiffType.HUMAN_EDIT,
        metadata: dict | None = None,
    ) -> DiffLog:
        """Record a human or agent edit to a document.

        Args:
            document_id: ID of the ProcessedDocument being edited.
            source_file_id: ID of the source File.
            before_text: Content before the edit.
            after_text: Content after the edit.
            justification: Reason for the edit.
            created_by: User or agent identifier.
            diff_type: Type of edit (human_edit or agent_edit).
            metadata: Optional extra structured data.

        Returns:
            The created DiffLog entry.
        """
        diff = DiffLog(
            document_id=document_id,
            source_file_id=source_file_id,
            diff_type=diff_type.value,
            before_text=before_text,
            after_text=after_text,
            justification=justification,
            metadata_=metadata,
            created_by=created_by,
        )
        self.db.add(diff)
        await self.db.flush()

        logger.info(
            "diff_edit_created",
            diff_id=str(diff.id),
            document_id=str(document_id),
            diff_type=diff_type.value,
            created_by=created_by,
        )
        return diff

    async def create_reprocess_diff(
        self,
        document_id: uuid.UUID,
        source_file_id: uuid.UUID,
        before_text: str,
        after_text: str,
        metadata: dict | None = None,
        justification: str = "Incremental reprocessing",
    ) -> DiffLog:
        """Record a reprocessing event.

        Args:
            document_id: ID of the ProcessedDocument.
            source_file_id: ID of the source File.
            before_text: Content before reprocessing.
            after_text: Content after reprocessing.
            metadata: Delta statistics (unchanged/modified/added/removed counts).
            justification: Reason for reprocessing.

        Returns:
            The created DiffLog entry.
        """
        diff = DiffLog(
            document_id=document_id,
            source_file_id=source_file_id,
            diff_type=DiffType.REPROCESSING.value,
            before_text=before_text,
            after_text=after_text,
            justification=justification,
            metadata_=metadata,
            created_by="system",
        )
        self.db.add(diff)
        await self.db.flush()

        logger.info(
            "diff_reprocess_created",
            diff_id=str(diff.id),
            document_id=str(document_id),
            source_file_id=str(source_file_id),
        )
        return diff

    # ── Query Methods ─────────────────────────────────────────────────────

    async def get_history(
        self,
        document_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[DiffLog]:
        """Retrieve the diff history for a document, newest first.

        Args:
            document_id: ID of the ProcessedDocument.
            limit: Maximum number of entries to return.

        Returns:
            Ordered list of DiffLog entries (newest first).
        """
        stmt = (
            select(DiffLog)
            .where(DiffLog.document_id == document_id)
            .order_by(DiffLog.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_file_history(
        self,
        source_file_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[DiffLog]:
        """Retrieve the diff history for all documents from a source file.

        Args:
            source_file_id: ID of the source File.
            limit: Maximum number of entries to return.

        Returns:
            Ordered list of DiffLog entries (newest first).
        """
        stmt = (
            select(DiffLog)
            .where(DiffLog.source_file_id == source_file_id)
            .order_by(DiffLog.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ── Static Utility Methods ────────────────────────────────────────────

    @staticmethod
    def compute_diff(before: str, after: str) -> list[dict]:
        """Compute structured diff operations between two texts.

        Args:
            before: The original text.
            after: The modified text.

        Returns:
            List of diff operation dicts with keys:
            - op: "equal", "insert", "delete", "replace"
            - before_start, before_end: line range in the original
            - after_start, after_end: line range in the modified
            - lines: affected lines (for insert/delete/replace)
        """
        before_lines = before.splitlines(keepends=True)
        after_lines = after.splitlines(keepends=True)

        matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
        ops: list[dict] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            op: dict = {
                "op": tag,
                "before_start": i1,
                "before_end": i2,
                "after_start": j1,
                "after_end": j2,
            }
            if tag == "replace":
                op["removed"] = before_lines[i1:i2]
                op["added"] = after_lines[j1:j2]
            elif tag == "insert":
                op["added"] = after_lines[j1:j2]
            elif tag == "delete":
                op["removed"] = before_lines[i1:i2]

            ops.append(op)

        logger.debug(
            "diff_computed",
            before_lines=len(before_lines),
            after_lines=len(after_lines),
            ops=len([o for o in ops if o["op"] != "equal"]),
        )
        return ops

    @staticmethod
    def compute_similarity(before: str, after: str) -> float:
        """Compute similarity ratio between two texts.

        Args:
            before: The original text.
            after: The modified text.

        Returns:
            Float between 0.0 (completely different) and 1.0 (identical).
        """
        return difflib.SequenceMatcher(None, before, after).ratio()

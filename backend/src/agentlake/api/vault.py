"""Vault router — file upload, download, tagging, and reprocessing.

Handles the raw file lifecycle: upload to MinIO, soft-delete, tag
management, and triggering (re)processing via Celery workers.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Body, Depends, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentlake.config import get_settings
from agentlake.core.auth import require_role
from agentlake.core.database import get_db
from agentlake.core.exceptions import ConflictError, NotFoundError, ValidationError
from agentlake.core.pagination import apply_cursor_pagination, encode_cursor
from agentlake.models.file import File, FileStatus
from agentlake.models.folder import Folder
from agentlake.models.tag import FileTag, Tag
from agentlake.schemas.common import Meta, PaginatedMeta, PaginatedResponse, ResponseEnvelope
from agentlake.schemas.file import FileListParams, FileResponse, FileUploadResponse
from agentlake.schemas.folder import (
    FileMoveRequest,
    FolderCreate,
    FolderDetailResponse,
    FolderMoveRequest,
    FolderResponse,
    FolderTreeNode,
    FolderUpdate,
)
from agentlake.schemas.tag import TagAssignment, TagCreate, TagResponse, TagWithCount
from agentlake.services.storage import StorageService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/vault", tags=["vault"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_request_id(request) -> str:  # noqa: ANN001
    """Extract X-Request-ID from the request, falling back to a new UUID."""
    return request.headers.get("X-Request-ID", str(uuid.uuid4()))


def _make_meta(request) -> Meta:  # noqa: ANN001
    return Meta(request_id=_get_request_id(request))


def _storage_service() -> StorageService:
    """Build a StorageService from current settings."""
    return StorageService(get_settings())


# ── File Upload ──────────────────────────────────────────────────────────────


@router.post(
    "/upload",
    response_model=ResponseEnvelope[FileUploadResponse],
    status_code=201,
    summary="Upload a file for processing",
)
async def upload_file(
    file: UploadFile,
    tags: str | None = Form(None),
    folder_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[FileUploadResponse]:
    """Upload a raw file to the vault and enqueue it for processing.

    Accepts multipart/form-data with the file and an optional comma-separated
    list of tag names.  Duplicate files (by SHA-256 hash) are rejected.
    """
    from starlette.requests import Request as StarletteRequest

    # The ``request`` parameter name shadows UploadFile; access the real
    # ASGI request via the dependency injection scope.  FastAPI names the
    # UploadFile param "request" here -- we alias the starlette request
    # from the api_key dependency's underlying request object.

    file_bytes = await file.read()
    if not file_bytes:
        raise ValidationError("Uploaded file is empty")

    # 1. Compute SHA-256
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    # 2. Check for duplicate hash
    dup_stmt = select(File).where(
        File.sha256_hash == sha256_hash,
        File.deleted_at.is_(None),
    )
    dup_result = await db.execute(dup_stmt)
    existing = dup_result.scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            f"Duplicate file detected: a file with SHA-256 {sha256_hash[:16]}... "
            f"already exists (id={existing.id})"
        )

    # 3. Generate storage key
    file_id = uuid.uuid4()
    original_filename = file.filename or "unnamed"
    storage_key = f"{file_id}/{original_filename}"

    # 4. Upload to MinIO
    storage = _storage_service()
    await storage.upload_file(
        storage_key=storage_key,
        data=io.BytesIO(file_bytes),
        size=len(file_bytes),
        content_type=file.content_type or "application/octet-stream",
    )

    # 4b. Validate folder if specified
    resolved_folder_id: uuid.UUID | None = None
    if folder_id:
        try:
            resolved_folder_id = uuid.UUID(folder_id)
        except ValueError:
            raise ValidationError(f"Invalid folder_id: {folder_id}")
        folder_stmt = select(Folder).where(Folder.id == resolved_folder_id)
        folder_result = await db.execute(folder_stmt)
        if folder_result.scalar_one_or_none() is None:
            raise NotFoundError(f"Folder {folder_id} not found")

    # 5. Create File record
    db_file = File(
        id=file_id,
        filename=original_filename,
        original_filename=original_filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(file_bytes),
        sha256_hash=sha256_hash,
        storage_key=storage_key,
        status=FileStatus.PENDING.value,
        uploaded_by=api_key.name if hasattr(api_key, "name") else str(api_key.id),
        folder_id=resolved_folder_id,
    )
    db.add(db_file)
    await db.flush()

    # 6. Parse and attach tags
    if tags:
        tag_names = [t.strip().lower() for t in tags.split(",") if t.strip()]
        for tag_name in tag_names:
            tag_stmt = select(Tag).where(Tag.name == tag_name)
            tag_result = await db.execute(tag_stmt)
            tag_obj = tag_result.scalar_one_or_none()
            if tag_obj is None:
                tag_obj = Tag(name=tag_name)
                db.add(tag_obj)
                await db.flush()
            file_tag = FileTag(
                file_id=db_file.id,
                tag_id=tag_obj.id,
                assigned_by=api_key.name if hasattr(api_key, "name") else "api",
            )
            db.add(file_tag)

    await db.flush()

    # 7. Enqueue processing task via Celery
    processing_task_id: str | None = None
    try:
        from agentlake.workers.celery_app import celery_app

        result = celery_app.send_task(
            "process_file",
            args=[str(db_file.id)],
            queue="default",
        )
        processing_task_id = result.id
    except Exception:
        logger.warning(
            "celery_enqueue_failed",
            file_id=str(db_file.id),
            exc_info=True,
        )

    # Reload with tags
    await db.refresh(db_file)

    logger.info(
        "file_uploaded",
        file_id=str(db_file.id),
        filename=original_filename,
        size_bytes=len(file_bytes),
        task_id=processing_task_id,
    )

    file_response = FileResponse.model_validate(db_file)
    upload_response = FileUploadResponse(
        file=file_response,
        processing_task_id=processing_task_id,
    )

    from starlette.requests import Request

    # Build meta from structlog contextvars (request_id is set by middleware)
    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=upload_response,
        meta=Meta(request_id=request_id),
    )


# ── List Files ───────────────────────────────────────────────────────────────


@router.get(
    "/files",
    response_model=PaginatedResponse[FileResponse],
    summary="List files with filtering and pagination",
)
async def list_files(
    params: FileListParams = Depends(),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> PaginatedResponse[FileResponse]:
    """List uploaded files with cursor-based pagination and filtering."""
    stmt = select(File).where(File.deleted_at.is_(None))

    if params.status:
        stmt = stmt.where(File.status == params.status)
    if params.content_type:
        stmt = stmt.where(File.content_type == params.content_type)
    if params.tag:
        stmt = (
            stmt.join(FileTag, FileTag.file_id == File.id)
            .join(Tag, Tag.id == FileTag.tag_id)
            .where(Tag.name == params.tag.lower())
        )

    # Determine sort column
    sort_column = getattr(File, params.sort_by, File.created_at)
    stmt = apply_cursor_pagination(
        stmt,
        cursor=params.cursor,
        limit=params.limit,
        order_column=sort_column,
        sort_order=params.sort_order,
    )
    stmt = stmt.options(selectinload(File.tags))

    result = await db.execute(stmt)
    files = list(result.scalars().unique().all())

    has_more = len(files) > params.limit
    if has_more:
        files = files[: params.limit]

    next_cursor: str | None = None
    if has_more and files:
        last_val = getattr(files[-1], params.sort_by, files[-1].created_at)
        next_cursor = encode_cursor({params.sort_by: last_val})

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return PaginatedResponse(
        data=[FileResponse.model_validate(f) for f in files],
        meta=PaginatedMeta(
            request_id=request_id,
            cursor=next_cursor,
            has_more=has_more,
        ),
    )


# ── Get File ─────────────────────────────────────────────────────────────────


@router.get(
    "/files/{file_id}",
    response_model=ResponseEnvelope[FileResponse],
    summary="Get a file by ID",
)
async def get_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[FileResponse]:
    """Retrieve metadata for a single file."""
    stmt = (
        select(File)
        .where(File.id == file_id, File.deleted_at.is_(None))
        .options(selectinload(File.tags))
    )
    result = await db.execute(stmt)
    db_file = result.scalar_one_or_none()
    if db_file is None:
        raise NotFoundError(f"File {file_id} not found")

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=FileResponse.model_validate(db_file),
        meta=Meta(request_id=request_id),
    )


# ── Download File ────────────────────────────────────────────────────────────


@router.get(
    "/files/{file_id}/download",
    summary="Download raw file from MinIO",
)
async def download_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> StreamingResponse:
    """Download the raw file from object storage.

    Returns a StreamingResponse with the original content type.
    """
    stmt = select(File).where(File.id == file_id, File.deleted_at.is_(None))
    result = await db.execute(stmt)
    db_file = result.scalar_one_or_none()
    if db_file is None:
        raise NotFoundError(f"File {file_id} not found")

    storage = _storage_service()
    file_bytes = await storage.download_file(db_file.storage_key)

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=db_file.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{db_file.original_filename}"',
            "Content-Length": str(db_file.size_bytes),
        },
    )


# ── Delete File ──────────────────────────────────────────────────────────────


@router.delete(
    "/files/{file_id}",
    response_model=ResponseEnvelope[dict],
    summary="Soft delete a file",
)
async def delete_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Soft-delete a file by setting deleted_at and status to deleting.

    Optionally triggers background cleanup of the MinIO object.
    """
    stmt = select(File).where(File.id == file_id, File.deleted_at.is_(None))
    result = await db.execute(stmt)
    db_file = result.scalar_one_or_none()
    if db_file is None:
        raise NotFoundError(f"File {file_id} not found")

    db_file.deleted_at = datetime.now(timezone.utc)
    db_file.status = FileStatus.DELETING.value
    await db.flush()

    # Attempt background deletion from MinIO
    try:
        storage = _storage_service()
        await storage.delete_file(db_file.storage_key)
    except Exception:
        logger.warning(
            "minio_delete_failed",
            file_id=str(file_id),
            storage_key=db_file.storage_key,
            exc_info=True,
        )

    logger.info("file_deleted", file_id=str(file_id))

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data={"id": str(file_id), "status": "deleted"},
        meta=Meta(request_id=request_id),
    )


# ── Update File Tags ────────────────────────────────────────────────────────


@router.put(
    "/files/{file_id}/tags",
    response_model=ResponseEnvelope[FileResponse],
    summary="Replace tags on a file",
)
async def update_file_tags(
    file_id: uuid.UUID,
    body: TagAssignment,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[FileResponse]:
    """Replace all tags on a file with the provided tag IDs."""
    stmt = (
        select(File)
        .where(File.id == file_id, File.deleted_at.is_(None))
        .options(selectinload(File.tags))
    )
    result = await db.execute(stmt)
    db_file = result.scalar_one_or_none()
    if db_file is None:
        raise NotFoundError(f"File {file_id} not found")

    # Remove existing file_tags
    delete_stmt = select(FileTag).where(FileTag.file_id == file_id)
    delete_result = await db.execute(delete_stmt)
    for ft in delete_result.scalars().all():
        await db.delete(ft)

    # Add new tags
    for tag_id in body.tag_ids:
        tag_stmt = select(Tag).where(Tag.id == tag_id)
        tag_result = await db.execute(tag_stmt)
        tag_obj = tag_result.scalar_one_or_none()
        if tag_obj is None:
            raise NotFoundError(f"Tag {tag_id} not found")
        file_tag = FileTag(
            file_id=file_id,
            tag_id=tag_id,
            assigned_by=api_key.name if hasattr(api_key, "name") else "api",
        )
        db.add(file_tag)

    await db.flush()
    await db.refresh(db_file)

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=FileResponse.model_validate(db_file),
        meta=Meta(request_id=request_id),
    )


# ── List Tags ────────────────────────────────────────────────────────────────


@router.get(
    "/tags",
    response_model=ResponseEnvelope[list[TagWithCount]],
    summary="List all tags with file counts",
)
async def list_tags(
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[list[TagWithCount]]:
    """Return all tags with the number of files each is assigned to."""
    stmt = (
        select(
            Tag,
            func.count(FileTag.file_id).label("file_count"),
        )
        .outerjoin(FileTag, FileTag.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(func.count(FileTag.file_id).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    tags = []
    for tag, file_count in rows:
        tag_data = TagWithCount(
            id=tag.id,
            name=tag.name,
            description=tag.description,
            is_system=tag.is_system,
            created_at=tag.created_at,
            file_count=file_count,
        )
        tags.append(tag_data)

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=tags,
        meta=Meta(request_id=request_id),
    )


# ── Create Tag ───────────────────────────────────────────────────────────────


@router.post(
    "/tags",
    response_model=ResponseEnvelope[TagResponse],
    status_code=201,
    summary="Create a new tag",
)
async def create_tag(
    body: TagCreate,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin")),  # noqa: ANN001
) -> ResponseEnvelope[TagResponse]:
    """Create a new user-defined tag."""
    name = payload.name.strip().lower()

    # Check for duplicate
    dup_stmt = select(Tag).where(Tag.name == name)
    dup_result = await db.execute(dup_stmt)
    if dup_result.scalar_one_or_none() is not None:
        raise ConflictError(f"Tag '{name}' already exists")

    tag = Tag(name=name, description=payload.description)
    db.add(tag)
    await db.flush()

    logger.info("tag_created", tag_id=str(tag.id), name=name)

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=TagResponse.model_validate(tag),
        meta=Meta(request_id=request_id),
    )


# ── Reprocess File ───────────────────────────────────────────────────────────


@router.post(
    "/reprocess/{file_id}",
    response_model=ResponseEnvelope[dict],
    summary="Trigger reprocessing of a file",
)
async def reprocess_file(
    file_id: uuid.UUID,
    mode: str = Query("incremental", pattern="^(incremental|full)$"),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Enqueue a file for reprocessing.

    In ``incremental`` mode (default), only chunks whose content hash changed
    are re-summarized and re-embedded.  In ``full`` mode, the entire file is
    reprocessed from scratch.
    """
    stmt = select(File).where(File.id == file_id, File.deleted_at.is_(None))
    result = await db.execute(stmt)
    db_file = result.scalar_one_or_none()
    if db_file is None:
        raise NotFoundError(f"File {file_id} not found")

    if db_file.status not in (FileStatus.PROCESSED.value, FileStatus.FAILED.value):
        raise ValidationError(
            f"File must be in 'processed' or 'failed' status to reprocess, "
            f"current status: {db_file.status}"
        )

    # Update status
    db_file.status = FileStatus.PENDING.value
    db_file.processing_started_at = None
    db_file.processing_completed_at = None
    db_file.error_message = None
    await db.flush()

    # Enqueue reprocessing task
    task_id: str | None = None
    try:
        from agentlake.workers.celery_app import celery_app

        result = celery_app.send_task(
            "reprocess_file",
            args=[str(file_id)],
            kwargs={"mode": mode},
            queue="default",
        )
        task_id = result.id
    except Exception:
        logger.warning(
            "celery_reprocess_enqueue_failed",
            file_id=str(file_id),
            exc_info=True,
        )

    logger.info(
        "file_reprocess_enqueued",
        file_id=str(file_id),
        mode=mode,
        task_id=task_id,
    )

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data={
            "file_id": str(file_id),
            "mode": mode,
            "task_id": task_id,
            "status": "enqueued",
        },
        meta=Meta(request_id=request_id),
    )


# ── Folder Helpers ────────────────────────────────────────────────────────────


async def _compute_folder_path(db: AsyncSession, parent_id: uuid.UUID | None, name: str) -> str:
    """Build a materialized path string for a folder."""
    if parent_id is None:
        return f"/{name}"
    parent_stmt = select(Folder).where(Folder.id == parent_id)
    parent_result = await db.execute(parent_stmt)
    parent = parent_result.scalar_one_or_none()
    if parent is None:
        raise NotFoundError(f"Parent folder {parent_id} not found")
    return f"{parent.path}/{name}"


async def _update_descendant_paths(db: AsyncSession, folder: Folder) -> None:
    """Recursively update paths for all descendants of a folder.

    Called after a rename or move operation to keep materialized paths
    consistent with the adjacency-list hierarchy.
    """
    children_stmt = select(Folder).where(Folder.parent_id == folder.id)
    children_result = await db.execute(children_stmt)
    children = list(children_result.scalars().all())
    for child in children:
        child.path = f"{folder.path}/{child.name}"
        await _update_descendant_paths(db, child)


async def _build_folder_response(
    db: AsyncSession, folder: Folder
) -> FolderResponse:
    """Build a FolderResponse with computed file_count and subfolder_count."""
    file_count_stmt = select(func.count()).select_from(File).where(
        File.folder_id == folder.id, File.deleted_at.is_(None)
    )
    file_count_result = await db.execute(file_count_stmt)
    file_count = file_count_result.scalar() or 0

    subfolder_count_stmt = select(func.count()).select_from(Folder).where(
        Folder.parent_id == folder.id
    )
    subfolder_count_result = await db.execute(subfolder_count_stmt)
    subfolder_count = subfolder_count_result.scalar() or 0

    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        path=folder.path,
        description=folder.description,
        created_by=folder.created_by,
        ai_summary_id=folder.ai_summary_id,
        file_count=file_count,
        subfolder_count=subfolder_count,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


# ── Folder Endpoints ─────────────────────────────────────────────────────────


@router.post(
    "/folders",
    response_model=ResponseEnvelope[FolderResponse],
    status_code=201,
    summary="Create a new folder",
)
async def create_folder(
    payload: FolderCreate = Body(..., embed=False),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[FolderResponse]:
    """Create a folder in the vault hierarchy.

    If ``parent_id`` is provided, the folder is created as a child of that
    folder.  Otherwise it is created at the root level.
    """
    parent_id: uuid.UUID | None = None
    if payload.parent_id:
        try:
            parent_id = uuid.UUID(payload.parent_id)
        except ValueError:
            raise ValidationError(f"Invalid parent_id: {payload.parent_id}")

        # Verify parent exists
        parent_stmt = select(Folder).where(Folder.id == parent_id)
        parent_result = await db.execute(parent_stmt)
        if parent_result.scalar_one_or_none() is None:
            raise NotFoundError(f"Parent folder {payload.parent_id} not found")

    # Check for duplicate name under same parent
    dup_stmt = select(Folder).where(
        Folder.parent_id == parent_id, Folder.name == payload.name.strip()
    )
    dup_result = await db.execute(dup_stmt)
    if dup_result.scalar_one_or_none() is not None:
        raise ConflictError(
            f"A folder named '{payload.name.strip()}' already exists in this location"
        )

    path = await _compute_folder_path(db, parent_id, payload.name.strip())

    folder = Folder(
        name=payload.name.strip(),
        parent_id=parent_id,
        path=path,
        description=payload.description,
        created_by=api_key.name if hasattr(api_key, "name") else str(api_key.id),
    )
    db.add(folder)
    await db.flush()
    await db.refresh(folder)

    logger.info("folder_created", folder_id=str(folder.id), path=path)

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))
    folder_resp = await _build_folder_response(db, folder)

    return ResponseEnvelope(
        data=folder_resp,
        meta=Meta(request_id=request_id),
    )


@router.get(
    "/folders",
    response_model=ResponseEnvelope[list[FolderResponse]],
    summary="List folders",
)
async def list_folders(
    parent_id: str | None = Query(None, description="Parent folder ID. Omit for root folders."),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[list[FolderResponse]]:
    """List folders at a given level. If parent_id is omitted, list root folders."""
    resolved_parent: uuid.UUID | None = None
    if parent_id:
        try:
            resolved_parent = uuid.UUID(parent_id)
        except ValueError:
            raise ValidationError(f"Invalid parent_id: {parent_id}")

    stmt = select(Folder).where(Folder.parent_id == resolved_parent).order_by(Folder.name)
    result = await db.execute(stmt)
    folders = list(result.scalars().all())

    folder_responses = []
    for f in folders:
        folder_responses.append(await _build_folder_response(db, f))

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=folder_responses,
        meta=Meta(request_id=request_id),
    )


@router.get(
    "/folders/{folder_id}",
    response_model=ResponseEnvelope[FolderDetailResponse],
    summary="Get folder details",
)
async def get_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[FolderDetailResponse]:
    """Get a folder with its immediate children and files."""
    stmt = select(Folder).where(Folder.id == folder_id)
    result = await db.execute(stmt)
    folder = result.scalar_one_or_none()
    if folder is None:
        raise NotFoundError(f"Folder {folder_id} not found")

    # Get children
    children_stmt = select(Folder).where(Folder.parent_id == folder_id).order_by(Folder.name)
    children_result = await db.execute(children_stmt)
    children = list(children_result.scalars().all())

    # Get files in folder
    files_stmt = (
        select(File)
        .where(File.folder_id == folder_id, File.deleted_at.is_(None))
        .options(selectinload(File.tags))
        .order_by(File.created_at.desc())
    )
    files_result = await db.execute(files_stmt)
    files = list(files_result.scalars().unique().all())

    folder_resp = await _build_folder_response(db, folder)
    children_resp = []
    for c in children:
        children_resp.append(await _build_folder_response(db, c))

    files_resp = [FileResponse.model_validate(f) for f in files]

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=FolderDetailResponse(
            folder=folder_resp,
            children=children_resp,
            files=files_resp,
        ),
        meta=Meta(request_id=request_id),
    )


@router.get(
    "/folders/{folder_id}/tree",
    response_model=ResponseEnvelope[FolderTreeNode],
    summary="Get recursive folder tree",
)
async def get_folder_tree(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("viewer", "editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[FolderTreeNode]:
    """Get a recursive tree of subfolders starting from folder_id."""
    stmt = select(Folder).where(Folder.id == folder_id)
    result = await db.execute(stmt)
    folder = result.scalar_one_or_none()
    if folder is None:
        raise NotFoundError(f"Folder {folder_id} not found")

    async def build_tree(f: Folder) -> FolderTreeNode:
        children_stmt = select(Folder).where(Folder.parent_id == f.id).order_by(Folder.name)
        children_result = await db.execute(children_stmt)
        children = list(children_result.scalars().all())
        child_nodes = []
        for child in children:
            child_nodes.append(await build_tree(child))
        return FolderTreeNode(
            folder=await _build_folder_response(db, f),
            children=child_nodes,
        )

    tree = await build_tree(folder)

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=tree,
        meta=Meta(request_id=request_id),
    )


@router.put(
    "/folders/{folder_id}",
    response_model=ResponseEnvelope[FolderResponse],
    summary="Update folder metadata",
)
async def update_folder(
    folder_id: uuid.UUID,
    payload: FolderUpdate = Body(..., embed=False),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin")),  # noqa: ANN001
) -> ResponseEnvelope[FolderResponse]:
    """Rename a folder or update its description.

    If the name changes, all descendant materialized paths are recomputed.
    """
    stmt = select(Folder).where(Folder.id == folder_id)
    result = await db.execute(stmt)
    folder = result.scalar_one_or_none()
    if folder is None:
        raise NotFoundError(f"Folder {folder_id} not found")

    if payload.name is not None and payload.name.strip() != folder.name:
        new_name = payload.name.strip()
        # Check for duplicate name under same parent
        dup_stmt = select(Folder).where(
            Folder.parent_id == folder.parent_id,
            Folder.name == new_name,
            Folder.id != folder_id,
        )
        dup_result = await db.execute(dup_stmt)
        if dup_result.scalar_one_or_none() is not None:
            raise ConflictError(f"A folder named '{new_name}' already exists in this location")

        folder.name = new_name
        folder.path = await _compute_folder_path(db, folder.parent_id, new_name)
        await _update_descendant_paths(db, folder)

    if payload.description is not None:
        folder.description = payload.description

    await db.flush()
    await db.refresh(folder)

    logger.info("folder_updated", folder_id=str(folder_id))

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))
    folder_resp = await _build_folder_response(db, folder)

    return ResponseEnvelope(
        data=folder_resp,
        meta=Meta(request_id=request_id),
    )


@router.put(
    "/folders/{folder_id}/move",
    response_model=ResponseEnvelope[FolderResponse],
    summary="Move a folder to a new parent",
)
async def move_folder(
    folder_id: uuid.UUID,
    payload: FolderMoveRequest = Body(..., embed=False),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin")),  # noqa: ANN001
) -> ResponseEnvelope[FolderResponse]:
    """Move a folder to a new parent. Pass null parent_id to move to root."""
    stmt = select(Folder).where(Folder.id == folder_id)
    result = await db.execute(stmt)
    folder = result.scalar_one_or_none()
    if folder is None:
        raise NotFoundError(f"Folder {folder_id} not found")

    new_parent_id: uuid.UUID | None = None
    if payload.parent_id:
        try:
            new_parent_id = uuid.UUID(payload.parent_id)
        except ValueError:
            raise ValidationError(f"Invalid parent_id: {payload.parent_id}")

        # Prevent moving into self or descendant
        if new_parent_id == folder_id:
            raise ValidationError("Cannot move a folder into itself")

        # Check the target is not a descendant
        check_stmt = select(Folder).where(Folder.id == new_parent_id)
        check_result = await db.execute(check_stmt)
        target = check_result.scalar_one_or_none()
        if target is None:
            raise NotFoundError(f"Target folder {payload.parent_id} not found")
        if target.path.startswith(folder.path + "/"):
            raise ValidationError("Cannot move a folder into one of its descendants")

    # Check for name conflict in new location
    dup_stmt = select(Folder).where(
        Folder.parent_id == new_parent_id,
        Folder.name == folder.name,
        Folder.id != folder_id,
    )
    dup_result = await db.execute(dup_stmt)
    if dup_result.scalar_one_or_none() is not None:
        raise ConflictError(
            f"A folder named '{folder.name}' already exists in the target location"
        )

    folder.parent_id = new_parent_id
    folder.path = await _compute_folder_path(db, new_parent_id, folder.name)
    await _update_descendant_paths(db, folder)
    await db.flush()
    await db.refresh(folder)

    logger.info("folder_moved", folder_id=str(folder_id), new_parent_id=str(new_parent_id))

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))
    folder_resp = await _build_folder_response(db, folder)

    return ResponseEnvelope(
        data=folder_resp,
        meta=Meta(request_id=request_id),
    )


@router.delete(
    "/folders/{folder_id}",
    response_model=ResponseEnvelope[dict],
    summary="Delete a folder",
)
async def delete_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin")),  # noqa: ANN001
) -> ResponseEnvelope[dict]:
    """Delete a folder and all its subfolders.

    Files in deleted folders are moved to the root (folder_id set to NULL).
    Subfolders are cascade-deleted by the database.
    """
    stmt = select(Folder).where(Folder.id == folder_id)
    result = await db.execute(stmt)
    folder = result.scalar_one_or_none()
    if folder is None:
        raise NotFoundError(f"Folder {folder_id} not found")

    # Move all files in this folder (and descendant folders) to root
    # Find all descendant folder IDs via path prefix
    desc_stmt = select(Folder.id).where(Folder.path.startswith(folder.path))
    desc_result = await db.execute(desc_stmt)
    descendant_ids = [row[0] for row in desc_result.all()]

    if descendant_ids:
        from sqlalchemy import update

        await db.execute(
            update(File)
            .where(File.folder_id.in_(descendant_ids))
            .values(folder_id=None)
        )

    await db.delete(folder)
    await db.flush()

    logger.info("folder_deleted", folder_id=str(folder_id))

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data={"id": str(folder_id), "status": "deleted"},
        meta=Meta(request_id=request_id),
    )


# ── Move File to Folder ──────────────────────────────────────────────────────


@router.put(
    "/files/{file_id}/move",
    response_model=ResponseEnvelope[FileResponse],
    summary="Move a file to a folder",
)
async def move_file(
    file_id: uuid.UUID,
    payload: FileMoveRequest = Body(..., embed=False),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin", "agent")),  # noqa: ANN001
) -> ResponseEnvelope[FileResponse]:
    """Move a file to a folder, or to the root if folder_id is null."""
    stmt = (
        select(File)
        .where(File.id == file_id, File.deleted_at.is_(None))
        .options(selectinload(File.tags))
    )
    result = await db.execute(stmt)
    db_file = result.scalar_one_or_none()
    if db_file is None:
        raise NotFoundError(f"File {file_id} not found")

    new_folder_id: uuid.UUID | None = None
    if payload.folder_id:
        try:
            new_folder_id = uuid.UUID(payload.folder_id)
        except ValueError:
            raise ValidationError(f"Invalid folder_id: {payload.folder_id}")
        folder_stmt = select(Folder).where(Folder.id == new_folder_id)
        folder_result = await db.execute(folder_stmt)
        if folder_result.scalar_one_or_none() is None:
            raise NotFoundError(f"Folder {payload.folder_id} not found")

    db_file.folder_id = new_folder_id
    await db.flush()
    await db.refresh(db_file)

    logger.info(
        "file_moved",
        file_id=str(file_id),
        folder_id=str(new_folder_id),
    )

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))

    return ResponseEnvelope(
        data=FileResponse.model_validate(db_file),
        meta=Meta(request_id=request_id),
    )


# ── Folder Analysis ──────────────────────────────────────────────────────


@router.post(
    "/folders/{folder_id}/analyze",
    response_model=ResponseEnvelope[dict],
    summary="Trigger AI analysis for a folder",
)
async def analyze_folder_endpoint(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(require_role("editor", "admin", "agent")),
):
    """Generate an AI summary of a folder's contents using GPT-5.4."""
    from agentlake.models.folder import Folder

    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise NotFoundError(f"Folder not found: {folder_id}")

    try:
        from agentlake.workers.celery_app import celery_app
        result = celery_app.send_task("analyze_folder", kwargs={"folder_id": str(folder_id)}, queue="low")
        task_id = result.id
    except Exception:
        logger.warning("folder_analyze_enqueue_failed", exc_info=True)
        task_id = None

    request_id = structlog.contextvars.get_contextvars().get("request_id", str(uuid.uuid4()))
    return ResponseEnvelope(
        data={"status": "queued", "task_id": task_id, "folder": folder.name, "path": folder.path},
        meta=Meta(request_id=request_id),
    )

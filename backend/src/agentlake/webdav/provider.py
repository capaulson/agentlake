"""WsgiDAV provider that maps WebDAV operations to AgentLake vault.

Uses synchronous psycopg2 for DB access (WsgiDAV is WSGI/sync).
MinIO operations use asyncio.run() since they're independent.

Hooks fire on every file change:
    - File added → auto-process through GPT-5.4 pipeline
    - File modified → version tracking + reprocess
    - File deleted → soft delete + cleanup
    - Folder contents change → trigger folder AI analysis
    - All changes → Redis pub/sub notification to UI
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import uuid
from datetime import datetime, timezone

import structlog
from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider
from wsgidav.dav_error import HTTP_FORBIDDEN, DAVError

logger = structlog.get_logger(__name__)


def _get_db():
    """Get a sync psycopg2 connection."""
    import psycopg2
    import psycopg2.extras
    from agentlake.config import get_settings
    settings = get_settings()
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn


def _get_storage():
    from agentlake.config import get_settings
    from agentlake.services.storage import StorageService
    return StorageService(get_settings())


def _notify_change(event_type: str, data: dict):
    try:
        import redis
        from agentlake.config import get_settings
        r = redis.from_url(get_settings().REDIS_URL)
        r.publish("vault:changes", json.dumps({
            "event": event_type, "data": data, "source": "webdav",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        r.close()
    except Exception:
        pass


def _guess_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "md": "text/markdown", "txt": "text/plain", "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv", "json": "application/json", "yaml": "application/x-yaml",
        "html": "text/html", "py": "text/x-python", "js": "text/javascript",
        "png": "image/png", "jpg": "image/jpeg",
    }.get(ext, "application/octet-stream")


_IGNORED_FILES = {".DS_Store", ".Spotlight-V100", ".Trashes", ".fseventsd", "desktop.ini", "Thumbs.db"}


def _is_ignored(name: str) -> bool:
    """Filter out macOS/Windows system files."""
    return name in _IGNORED_FILES or name.startswith("._")


class VaultProvider(DAVProvider):
    def __init__(self):
        super().__init__()

    def get_resource_inst(self, path: str, environ: dict):
        path = path.rstrip("/") or "/"

        # Silently ignore macOS/Windows hidden files
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        if _is_ignored(name):
            return None

        if path == "/":
            return VaultFolder("/", None, self, is_root=True)

        conn = _get_db()
        try:
            cur = conn.cursor()

            # Try as folder
            cur.execute("SELECT id, name, path, parent_id, description, created_by, ai_summary_id, created_at, updated_at FROM folders WHERE path = %s", (path,))
            row = cur.fetchone()
            if row:
                folder = {"id": row[0], "name": row[1], "path": row[2], "parent_id": row[3],
                           "created_at": row[7], "updated_at": row[8]}
                return VaultFolder(path, folder, self)

            # Try as file
            parts = path.rsplit("/", 1)
            if len(parts) == 2:
                parent_path, filename = parts
                parent_path = parent_path or "/"

                if parent_path == "/":
                    cur.execute(
                        "SELECT id, filename, content_type, size_bytes, sha256_hash, storage_key, status, folder_id, created_at, updated_at "
                        "FROM files WHERE filename = %s AND folder_id IS NULL AND deleted_at IS NULL", (filename,))
                else:
                    cur.execute("SELECT id FROM folders WHERE path = %s", (parent_path,))
                    folder_row = cur.fetchone()
                    if folder_row:
                        cur.execute(
                            "SELECT id, filename, content_type, size_bytes, sha256_hash, storage_key, status, folder_id, created_at, updated_at "
                            "FROM files WHERE filename = %s AND folder_id = %s AND deleted_at IS NULL", (filename, folder_row[0]))
                    else:
                        return None

                file_row = cur.fetchone()
                if file_row:
                    file = {"id": file_row[0], "filename": file_row[1], "content_type": file_row[2],
                            "size_bytes": file_row[3], "sha256_hash": file_row[4], "storage_key": file_row[5],
                            "status": file_row[6], "folder_id": file_row[7],
                            "created_at": file_row[8], "updated_at": file_row[9]}
                    return VaultFile(path, file, self)
        finally:
            conn.close()

        return None


class VaultFolder(DAVCollection):
    def __init__(self, path, folder, provider, is_root=False):
        super().__init__(path, environ={"wsgidav.provider": provider})
        self._folder = folder
        self._provider = provider
        self._is_root = is_root
        self.provider = provider

    def get_display_info(self):
        return {"type": "Directory"}

    def get_member_names(self):
        conn = _get_db()
        try:
            cur = conn.cursor()
            names = []
            folder_id = self._folder["id"] if self._folder else None

            # Subfolders
            if self._is_root:
                cur.execute("SELECT name FROM folders WHERE parent_id IS NULL ORDER BY name")
            else:
                cur.execute("SELECT name FROM folders WHERE parent_id = %s ORDER BY name", (folder_id,))
            names.extend(r[0] for r in cur.fetchall() if not _is_ignored(r[0]))

            # Files
            if self._is_root:
                cur.execute("SELECT filename FROM files WHERE folder_id IS NULL AND deleted_at IS NULL ORDER BY filename")
            else:
                cur.execute("SELECT filename FROM files WHERE folder_id = %s AND deleted_at IS NULL ORDER BY filename", (folder_id,))
            names.extend(r[0] for r in cur.fetchall() if not _is_ignored(r[0]))

            return names
        finally:
            conn.close()

    def get_member(self, name):
        child_path = f"/{name}" if self._is_root else f"{self.path.rstrip('/')}/{name}"
        return self._provider.get_resource_inst(child_path, {})

    def create_empty_resource(self, name):
        folder_id = self._folder["id"] if self._folder else None
        file_id = str(uuid.uuid4())
        storage_key = f"{file_id}/{name}"

        conn = _get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO files (id, filename, original_filename, content_type, size_bytes, sha256_hash, storage_key, status, folder_id, uploaded_by) "
                "VALUES (%s, %s, %s, %s, 0, %s, %s, 'pending', %s, 'webdav')",
                (file_id, name, name, _guess_type(name), hashlib.sha256(b"").hexdigest(), storage_key, folder_id))
            conn.commit()
            logger.info("webdav_file_created", filename=name, file_id=file_id)
        finally:
            conn.close()

        child_path = f"/{name}" if self._is_root else f"{self.path.rstrip('/')}/{name}"
        file = {"id": uuid.UUID(file_id), "filename": name, "content_type": _guess_type(name),
                "size_bytes": 0, "sha256_hash": hashlib.sha256(b"").hexdigest(),
                "storage_key": storage_key, "folder_id": folder_id,
                "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}
        return VaultFile(child_path, file, self._provider)

    def create_collection(self, name):
        parent_id = self._folder["id"] if self._folder else None
        parent_path = self._folder["path"] if self._folder else ""
        new_path = f"{parent_path}/{name}"

        conn = _get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO folders (name, parent_id, path, created_by) VALUES (%s, %s, %s, 'webdav')",
                (name, parent_id, new_path))
            conn.commit()
            logger.info("webdav_folder_created", name=name, path=new_path)
            _notify_change("folder_created", {"name": name, "path": new_path})
        finally:
            conn.close()

    def support_recursive_move(self, dest_path):
        return True

    def support_recursive_delete(self):
        return True

    def move_recursive(self, dest_path):
        """MOVE folder — rename or reparent."""
        if self._is_root:
            raise DAVError(HTTP_FORBIDDEN)
        dest_path = dest_path.rstrip("/")
        parts = dest_path.rsplit("/", 1)
        new_name = parts[1] if len(parts) == 2 else dest_path.lstrip("/")
        dest_parent = parts[0] if len(parts) == 2 else "/"

        conn = _get_db()
        try:
            cur = conn.cursor()
            dest_parent_id = None
            if dest_parent and dest_parent != "/":
                cur.execute("SELECT id FROM folders WHERE path = %s", (dest_parent,))
                row = cur.fetchone()
                dest_parent_id = row[0] if row else None

            old_path = self._folder["path"]
            new_path = f"{dest_parent}/{new_name}" if dest_parent != "/" else f"/{new_name}"

            cur.execute("UPDATE folders SET name = %s, parent_id = %s, path = %s, updated_at = now() WHERE id = %s",
                        (new_name, dest_parent_id, new_path, str(self._folder["id"])))
            # Update all descendant paths
            cur.execute("UPDATE folders SET path = %s || substring(path from %s) WHERE path LIKE %s AND id != %s",
                        (new_path, len(old_path) + 1, f"{old_path}/%", str(self._folder["id"])))
            conn.commit()
            logger.info("webdav_folder_moved", old=old_path, new=new_path)
            _notify_change("folder_moved", {"old_path": old_path, "new_path": new_path})

        finally:
            conn.close()

    def delete(self):
        if self._is_root:
            raise DAVError(HTTP_FORBIDDEN)
        conn = _get_db()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM folders WHERE id = %s", (str(self._folder["id"]),))
            conn.commit()
            logger.info("webdav_folder_deleted", path=self._folder["path"])
            _notify_change("folder_deleted", {"path": self._folder["path"]})
        finally:
            conn.close()

    def get_creation_date(self):
        return self._folder["created_at"].timestamp() if self._folder and self._folder.get("created_at") else None

    def get_last_modified(self):
        ts = self._folder.get("updated_at") or self._folder.get("created_at") if self._folder else None
        return ts.timestamp() if ts else None


class VaultFile(DAVNonCollection):
    def __init__(self, path, file, provider):
        super().__init__(path, environ={"wsgidav.provider": provider})
        self._file = file
        self._provider = provider
        self.provider = provider

    def get_content_length(self):
        return self._file["size_bytes"]

    def get_content_type(self):
        return self._file["content_type"]

    def get_display_name(self):
        return self._file["filename"]

    def get_etag(self):
        return self._file["sha256_hash"]

    def get_creation_date(self):
        ts = self._file.get("created_at")
        return ts.timestamp() if ts else None

    def get_last_modified(self):
        ts = self._file.get("updated_at") or self._file.get("created_at")
        return ts.timestamp() if ts else None

    def support_etag(self):
        return True

    def support_ranges(self):
        return False

    def get_content(self):
        storage = _get_storage()
        data = asyncio.run(storage.download_file(self._file["storage_key"]))
        return io.BytesIO(data)

    def begin_write(self, content_type=None):
        return _WriteStream(self._file, self._provider)

    def copy_move_single(self, dest_path, is_move):
        """Handle MOVE and COPY for files (used by macOS Finder, Windows Explorer)."""
        dest_path = dest_path.rstrip("/")
        parts = dest_path.rsplit("/", 1)
        new_name = parts[1] if len(parts) == 2 else dest_path.lstrip("/")
        dest_parent = parts[0] if len(parts) == 2 else "/"

        conn = _get_db()
        try:
            cur = conn.cursor()

            # Resolve destination folder
            dest_folder_id = None
            if dest_parent and dest_parent != "/":
                cur.execute("SELECT id FROM folders WHERE path = %s", (dest_parent,))
                row = cur.fetchone()
                dest_folder_id = row[0] if row else None

            if is_move:
                # MOVE: update filename and folder_id in place
                cur.execute(
                    "UPDATE files SET filename = %s, original_filename = %s, folder_id = %s, updated_at = now() WHERE id = %s",
                    (new_name, new_name, dest_folder_id, str(self._file["id"])))
                conn.commit()
                logger.info("webdav_file_moved", filename=new_name, dest=dest_path)
                _notify_change("file_moved", {"file_id": str(self._file["id"]), "dest": dest_path})
            else:
                # COPY: create a new file record + copy MinIO object
                new_id = str(uuid.uuid4())
                new_key = f"{new_id}/{new_name}"
                cur.execute(
                    "INSERT INTO files (id, filename, original_filename, content_type, size_bytes, sha256_hash, storage_key, status, folder_id, uploaded_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'webdav')",
                    (new_id, new_name, new_name, self._file["content_type"], self._file["size_bytes"],
                     self._file["sha256_hash"], new_key, self._file.get("status", "processed"), dest_folder_id))
                conn.commit()
                # Copy the MinIO object
                try:
                    storage = _get_storage()
                    data = asyncio.run(storage.download_file(self._file["storage_key"]))
                    asyncio.run(storage.upload_file(new_key, io.BytesIO(data), len(data), self._file["content_type"]))
                except Exception as e:
                    logger.warning("webdav_copy_storage_failed", error=str(e))
                logger.info("webdav_file_copied", filename=new_name, dest=dest_path)


        finally:
            conn.close()

    def support_recursive_move(self, dest_path):
        """Tell WsgiDAV we handle MOVE ourselves."""
        return True

    def support_recursive_delete(self):
        return True

    def move_recursive(self, dest_path):
        """MOVE operation — used by Finder drag-drop and rename."""
        self.copy_move_single(dest_path, is_move=True)

    def copy_recursive(self, dest_path):
        """COPY operation."""
        self.copy_move_single(dest_path, is_move=False)

    def delete(self):
        conn = _get_db()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE files SET deleted_at = now(), status = 'deleting' WHERE id = %s", (self._file["id"],))
            conn.commit()
            logger.info("webdav_file_deleted", filename=self._file["filename"])
            _notify_change("file_deleted", {"filename": self._file["filename"], "file_id": str(self._file["id"])})
        finally:
            conn.close()


class _WriteStream(io.BytesIO):
    """Captures WebDAV writes and triggers all hooks on close."""

    def __init__(self, file, provider):
        super().__init__()
        self._file = file
        self._provider = provider

    def close(self):
        data = self.getvalue()
        super().close()

        file_id = str(self._file["id"])
        sha256 = hashlib.sha256(data).hexdigest()
        is_new = self._file["size_bytes"] == 0
        is_modified = sha256 != self._file["sha256_hash"]

        logger.info("webdav_file_written", filename=self._file["filename"],
                     size=len(data), is_new=is_new, is_modified=is_modified)

        # Upload to MinIO
        storage = _get_storage()
        asyncio.run(storage.upload_file(
            self._file["storage_key"], io.BytesIO(data), len(data),
            self._file.get("content_type", "application/octet-stream"),
        ))

        # Update DB
        conn = _get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE files SET size_bytes = %s, sha256_hash = %s, status = 'pending', updated_at = now() WHERE id = %s",
                (len(data), sha256, file_id))
            conn.commit()
        finally:
            conn.close()

        # ── HOOK 1: Auto-process / reprocess ─────────────────────────
        try:
            from agentlake.workers.celery_app import celery_app
            if is_new:
                celery_app.send_task("process_file", args=[str(file_id)], queue="default")
                logger.info("webdav_hook_process", file_id=str(file_id))
            elif is_modified:
                celery_app.send_task("reprocess_file", args=[str(file_id)], kwargs={"mode": "incremental"}, queue="high")
                logger.info("webdav_hook_reprocess", file_id=str(file_id))
        except Exception as e:
            logger.warning("webdav_hook_process_failed", error=str(e))

        # ── HOOK 2: Folder analysis on change ────────────────────────
        if self._file.get("folder_id"):
            try:
                from agentlake.workers.celery_app import celery_app
                celery_app.send_task("analyze_folder", kwargs={"folder_id": str(self._file["folder_id"])}, queue="low")
                logger.info("webdav_hook_folder_analysis", folder_id=str(self._file["folder_id"]))
            except Exception as e:
                logger.warning("webdav_hook_folder_failed", error=str(e))

        # ── HOOK 3: Real-time UI sync ────────────────────────────────
        _notify_change("file_updated" if is_modified else "file_created", {
            "file_id": str(file_id), "filename": self._file["filename"],
            "folder_id": str(self._file.get("folder_id")) if self._file.get("folder_id") else None,
            "size": len(data),
        })

        # ── HOOK 4: Version tracking ─────────────────────────────────
        if is_modified and not is_new:
            conn = _get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO diff_logs (id, source_file_id, diff_type, before_text, after_text, justification, created_by) "
                    "VALUES (%s, %s, 'human_edit', %s, %s, 'Modified via WebDAV network drive', 'webdav')",
                    (str(uuid.uuid4()), file_id,
                     f"[Previous: {self._file['sha256_hash'][:16]}, {self._file['size_bytes']} bytes]",
                     f"[New: {sha256[:16]}, {len(data)} bytes]"))
                conn.commit()
                logger.info("webdav_hook_version", file_id=str(file_id))
            finally:
                conn.close()

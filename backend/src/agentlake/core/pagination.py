"""Cursor-based pagination utilities."""

from __future__ import annotations

import base64
import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import Column, Select, asc, desc

T = TypeVar("T")


# ── Cursor Encoding ─────────────────────────────────────────────────────────


def encode_cursor(values: dict[str, Any]) -> str:
    """Encode a dict of column values into an opaque cursor string.

    Args:
        values: Mapping of column names to their values (must be JSON-serializable).

    Returns:
        URL-safe base64 encoded cursor.
    """
    payload = json.dumps(values, default=str).encode()
    return base64.urlsafe_b64encode(payload).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode an opaque cursor string back into column values.

    Args:
        cursor: Base64-encoded cursor produced by :func:`encode_cursor`.

    Returns:
        Dict of column names to values.

    Raises:
        ValueError: If the cursor is malformed.
    """
    try:
        payload = base64.urlsafe_b64decode(cursor.encode())
        return json.loads(payload)  # type: ignore[no-any-return]
    except Exception as exc:
        raise ValueError(f"Invalid cursor: {exc}") from exc


# ── Pydantic Response Models ────────────────────────────────────────────────


class CursorMeta(BaseModel):
    """Metadata for cursor-paginated responses."""

    cursor: str | None = Field(
        None, description="Opaque cursor for fetching the next page"
    )
    has_more: bool = Field(
        ..., description="Whether additional pages exist"
    )
    total_count: int | None = Field(
        None, description="Total matching items (omitted when expensive to compute)"
    )


class CursorPage(BaseModel, Generic[T]):
    """Generic cursor-paginated response envelope."""

    data: list[T]
    meta: CursorMeta


# ── Query Helpers ────────────────────────────────────────────────────────────


def apply_cursor_pagination(
    query: Select[Any],
    cursor: str | None,
    limit: int,
    order_column: Column[Any],
    sort_order: str = "desc",
) -> Select[Any]:
    """Apply cursor-based pagination to a SQLAlchemy ``Select``.

    The function:

    1. Orders the query by *order_column* in the requested direction.
    2. If a *cursor* is provided, filters to rows **after** the cursor position.
    3. Fetches ``limit + 1`` rows so the caller can determine ``has_more``.

    Args:
        query: An existing SQLAlchemy select statement.
        cursor: Opaque cursor string (or ``None`` for the first page).
        limit: Maximum items per page.
        order_column: The SQLAlchemy column to sort / paginate on.
        sort_order: ``"asc"`` or ``"desc"``.

    Returns:
        Modified select statement.  The caller should fetch ``limit + 1``
        rows, then check if the extra row exists to set ``has_more``.
    """
    direction = asc if sort_order == "asc" else desc
    query = query.order_by(direction(order_column))

    if cursor is not None:
        values = decode_cursor(cursor)
        col_name = order_column.key  # type: ignore[union-attr]
        cursor_value = values.get(col_name)
        if cursor_value is not None:
            if sort_order == "asc":
                query = query.where(order_column > cursor_value)
            else:
                query = query.where(order_column < cursor_value)

    # Fetch one extra row to determine has_more
    query = query.limit(limit + 1)
    return query

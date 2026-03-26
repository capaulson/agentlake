"""Authentication and authorization utilities."""

from __future__ import annotations

import enum
import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import Depends, Request
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentlake.config import get_settings
from agentlake.core.database import get_db

logger = structlog.get_logger(__name__)


# ── Roles ────────────────────────────────────────────────────────────────────


class Role(str, enum.Enum):
    """Authorization roles in order of decreasing privilege."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    AGENT = "agent"


# ── API-key hashing ─────────────────────────────────────────────────────────


def hash_api_key(key: str, salt: str) -> str:
    """Produce a hex-encoded SHA-256 hash of *key* using *salt*.

    Args:
        key: The raw API key.
        salt: Application-level salt from settings.

    Returns:
        Hex-encoded hash string.
    """
    return hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()


def verify_api_key(key: str, key_hash: str, salt: str) -> bool:
    """Constant-time comparison of a raw key against its stored hash.

    Args:
        key: The raw API key to verify.
        key_hash: The stored hex-encoded hash.
        salt: Application-level salt from settings.

    Returns:
        True if the key matches.
    """
    computed = hash_api_key(key, salt)
    return hmac.compare_digest(computed, key_hash)


# ── JWT tokens ───────────────────────────────────────────────────────────────


def create_jwt_token(
    data: dict[str, Any],
    secret: str,
    algorithm: str = "HS256",
    expires_hours: int = 24,
) -> str:
    """Create a signed JWT token.

    Args:
        data: Payload claims.
        secret: Signing secret.
        algorithm: JWT algorithm.
        expires_hours: Hours until expiry.

    Returns:
        Encoded JWT string.
    """
    payload = data.copy()
    payload["exp"] = datetime.now(UTC) + timedelta(hours=expires_hours)
    payload["iat"] = datetime.now(UTC)
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_jwt_token(
    token: str,
    secret: str,
    algorithm: str = "HS256",
) -> dict[str, Any]:
    """Decode and verify a JWT token.

    Args:
        token: Encoded JWT string.
        secret: Signing secret.
        algorithm: JWT algorithm.

    Returns:
        Decoded payload dict.

    Raises:
        agentlake.core.exceptions.AuthorizationError: If the token is invalid or expired.
    """
    from agentlake.core.exceptions import AuthorizationError

    try:
        return jwt.decode(token, secret, algorithms=[algorithm])
    except JWTError as exc:
        raise AuthorizationError(detail=f"Invalid or expired token: {exc}") from exc


# ── FastAPI dependencies ─────────────────────────────────────────────────────


async def get_current_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """FastAPI dependency that authenticates via X-API-Key header.

    Looks up the hashed key in the ``api_keys`` table and returns the
    corresponding :class:`ApiKey` model instance.

    Raises:
        AuthorizationError: If the header is missing or the key is unknown.
    """
    from agentlake.core.exceptions import AuthorizationError

    raw_key = request.headers.get("X-API-Key")
    if not raw_key:
        raise AuthorizationError(detail="Missing X-API-Key header")

    settings = get_settings()
    hashed = hash_api_key(raw_key, settings.API_KEY_SALT)

    # Deferred import to avoid circular dependency with models
    from agentlake.models.api_key import ApiKey

    stmt = select(ApiKey).where(
        ApiKey.key_hash == hashed,
        ApiKey.is_active.is_(True),
    )
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if api_key is None:
        logger.warning("api_key.auth_failed", key_prefix=raw_key[:8])
        raise AuthorizationError(detail="Invalid API key")

    logger.info(
        "api_key.authenticated",
        api_key_id=str(api_key.id),
        role=api_key.role,
    )
    return api_key


def require_role(*roles: str) -> Callable[..., Any]:
    """Return a FastAPI dependency that checks the API key's role.

    Usage::

        @router.get("/admin-only")
        async def admin_endpoint(
            api_key = Depends(require_role("admin")),
        ):
            ...

    Args:
        *roles: Allowed role names (e.g. ``"admin"``, ``"editor"``).

    Returns:
        A FastAPI-compatible dependency callable.
    """
    allowed = {r.value if isinstance(r, Role) else r for r in roles}

    async def _check_role(
        api_key: Any = Depends(get_current_api_key),
    ) -> Any:
        from agentlake.core.exceptions import AuthorizationError

        key_role = api_key.role if isinstance(api_key.role, str) else api_key.role.value
        if key_role not in allowed:
            raise AuthorizationError(
                detail=f"Role '{key_role}' is not authorized. Required: {allowed}"
            )
        return api_key

    return _check_role

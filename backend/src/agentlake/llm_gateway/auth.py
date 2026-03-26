"""Service-token authentication for the LLM Gateway."""

from __future__ import annotations

import hmac

import structlog
from fastapi import Depends, HTTPException, Request

logger = structlog.get_logger(__name__)

# The expected token is set at startup and stored here.
_expected_token: str = ""


def set_service_token(token: str) -> None:
    """Configure the expected service token (called once at app startup).

    Args:
        token: The shared secret that internal services must present.
    """
    global _expected_token  # noqa: PLW0603
    _expected_token = token


async def verify_service_token(request: Request) -> str:
    """FastAPI dependency that validates the ``X-Service-Token`` header.

    Returns the caller identity (currently the token itself; could be
    extended to decode a JWT in the future).

    Raises:
        HTTPException: 401 if the header is missing or invalid.
    """
    token = request.headers.get("X-Service-Token", "")

    if not token:
        logger.warning("auth_missing_token", path=request.url.path)
        raise HTTPException(status_code=401, detail="Missing X-Service-Token header")

    if not _expected_token:
        # If no token is configured, skip auth (development mode).
        logger.debug("auth_no_token_configured_skipping")
        return "dev"

    # Constant-time comparison to prevent timing attacks.
    if not hmac.compare_digest(token, _expected_token):
        logger.warning("auth_invalid_token", path=request.url.path)
        raise HTTPException(status_code=401, detail="Invalid service token")

    return "authenticated"
